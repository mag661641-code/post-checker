"""Экран «Проверка постов» — дизайн-система ИМП.

Шапка (месяц, навигация, орфография, отчёт) → переключатель «Посты / Замечания».
Вкладка «Посты»: KPI-карточки-фильтры, строка фильтров, список + карточка поста.
Вкладка «Замечания»: правила по уровням + разбор выбранного правила.
Меняется только интерфейс; проверки, загрузка данных и отчёт — из пакета checker.
"""
from __future__ import annotations

import calendar as _cal
import datetime as dt
import html
import re

import pandas as pd
import streamlit as st

from checker import config_mod
from checker.models import Issue, Level, PostRecord
from ui import common as C

# Названия правил по коду (для карточки и вкладки «Замечания»).
try:
    from ui.settings import CHECK_META
    _CODE_NAME: dict[str, str] = {}
    for _key, _sec, _name, _expl, _codes, _dl in CHECK_META:
        for _c in _codes:
            _CODE_NAME.setdefault(_c, _name)
except Exception:  # noqa: BLE001
    _CODE_NAME = {}
_CODE_NAME.setdefault("spell_error", "Орфографическая ошибка")

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF️]")

# Цвета уровней замечаний (дизайн-система ИМП).
_LVL = {
    Level.ERROR: {"dot": "#D42525", "bg": "#EBD7D7", "fg": "#C01616",
                  "name": "Ошибка", "plural": "Ошибки", "code": "err"},
    Level.WARNING: {"dot": "#F0AC17", "bg": "#FFE26C", "fg": "#1E1E1E",
                    "name": "Предупреждение", "plural": "Предупреждения",
                    "code": "warn"},
    Level.ADVICE: {"dot": "#1D42A5", "bg": "#DADFEC", "fg": "#1D42A5",
                   "name": "Совет", "plural": "Советы", "code": "tip"},
}
_LEVELS = [Level.ERROR, Level.WARNING, Level.ADVICE]
_SEV_LEVEL = {"err": Level.ERROR, "warn": Level.WARNING, "tip": Level.ADVICE}

_POSTS_CSS = """
<style>
/* KPI-карточки-фильтры */
.st-key-kpi_all button,.st-key-kpi_err button,.st-key-kpi_warn button,.st-key-kpi_tip button{
  min-height:88px;display:flex;flex-direction:column;align-items:flex-start;gap:2px;
  text-align:left;border:1px solid #DFDFDF;border-radius:4px;background:#FEFEFE;
  padding:14px 16px;box-shadow:none;font-weight:400;color:#1E1E1E}
.st-key-kpi_all button p,.st-key-kpi_err button p,.st-key-kpi_warn button p,
.st-key-kpi_tip button p{text-align:left;width:100%;margin:0}
.st-key-kpi_err button{border-left:3px solid #D42525}
.st-key-kpi_warn button{border-left:3px solid #F0AC17}
.st-key-kpi_tip button{border-left:3px solid #1D42A5}
.st-key-kpi_all button:hover,.st-key-kpi_err button:hover,
.st-key-kpi_warn button:hover,.st-key-kpi_tip button:hover{border-color:#1D42A5}
</style>
"""


def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text or "").strip()


def _text_preview(post: PostRecord, limit: int = 70) -> str:
    t = _strip_emoji(post.text)
    if not t:
        return "(текст не заполнен)"
    t = re.sub(r"\s+", " ", t)
    return t[:limit] + ("…" if len(t) > limit else "")


def _rule_name(code: str, fallback: str = "") -> str:
    return _CODE_NAME.get(code, fallback or code)


def _post_sev(issues: list[Issue]):
    for lvl in _LEVELS:
        if any(i.level == lvl for i in issues):
            return lvl
    return None


def _square(color: str, size: int = 10) -> str:
    return (f'<span style="display:inline-block;width:{size}px;height:{size}px;'
            f'border-radius:2px;background:{color};margin-right:8px;'
            f'vertical-align:middle"></span>')


def _tag(level: Level) -> str:
    d = _LVL[level]
    return (f'<span style="display:inline-flex;align-items:center;height:22px;'
            f'padding:0 8px;border-radius:4px;background:{d["bg"]};'
            f'color:{d["fg"]};font-size:12px;font-weight:600;'
            f'white-space:nowrap">{d["name"]}</span>')


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def render() -> None:
    file_bytes = st.session_state.get("file_bytes")
    if not file_bytes:
        C.empty_no_file()
        return

    st.markdown(_POSTS_CSS, unsafe_allow_html=True)

    data = C.build_app_data(file_bytes)
    C.ensure_period(data)
    period = C.current_period()

    # --- состояние экрана ---
    # отложенное переключение вида (нельзя менять ключ виджета после его создания)
    pending = st.session_state.pop("force_view", None)
    if pending:
        st.session_state["posts_view"] = pending
    st.session_state.setdefault("posts_view", "Посты")
    st.session_state.setdefault("sev", "all")
    st.session_state.setdefault("flt_brand", "Все")
    st.session_state.setdefault("flt_status", "Все")
    st.session_state.setdefault("flt_only", True)
    st.session_state.setdefault("flt_sort", "По дате")
    st.session_state.setdefault("flt_search", "")
    st.session_state.setdefault("verified", set())
    st.session_state.setdefault("sel_post", None)
    st.session_state.setdefault("sel_rule", None)

    brand_codes = list(data.cfg["brands"].keys())
    brand_sel = st.session_state.get("flt_brand") or "Все"
    brands = brand_codes if brand_sel == "Все" else [brand_sel]
    status_sel = st.session_state.get("flt_status") or "Все"
    status = [] if status_sel == "Все" else [status_sel]
    search = (st.session_state.get("flt_search") or "").strip().lower()

    base = C.apply_filters(data, {"brands": brands, "status": status,
                                  "search": search, "levels": [],
                                  "only_issues": False}, period)

    # --- шапка ---
    _header(data, period, base)

    # --- переключатель вида ---
    view = st.segmented_control(
        "Вид", ["Посты", "Календарь", "Замечания"], key="posts_view",
        label_visibility="collapsed")
    view = view or "Посты"

    if view == "Посты":
        _view_posts(data, base, period)
    elif view == "Календарь":
        _view_calendar(data, base, period)
    else:
        _view_issues(data, base, period)


# ---------------------------------------------------------------------------
# Шапка
# ---------------------------------------------------------------------------
def _header(data: C.AppData, period, base) -> None:
    today = C.moscow_today()
    if isinstance(period, tuple):
        year, month = period
    else:
        year, month = today.year, today.month

    note = st.session_state.get("period_note")
    if note:
        st.info(note)

    py, pm = C._shift_month(year, month, -1)
    ny, nm = C._shift_month(year, month, +1)

    # одна строка: месяц · ← · → · Проверить орфографию · Скачать отчёт
    c = st.columns([5, 1, 1, 3, 3], vertical_alignment="center")
    c[0].markdown(f"## {C.fmt_month(year, month)}")
    if c[1].button("←", key="mprev", help=C.MONTHS_NOM[pm],
                   use_container_width=True):
        _set_period(py, pm)
    if c[2].button("→", key="mnext", help=C.MONTHS_NOM[nm],
                   use_container_width=True):
        _set_period(ny, nm)
    if c[3].button("Проверить орфографию", key="spell_all_btn",
                   type="secondary", use_container_width=True):
        _spell_all_fragment(data, base)
    report = C.build_report_bytes(data, base, period)
    if report:
        xlsx, fname, label = report
        c[4].download_button(label, data=xlsx, file_name=fname,
                             mime=C.REPORT_MIME, type="primary",
                             use_container_width=True, key="dl_report")

    total = len(C.posts_in_period(data, period))
    no_date = [p for p in data.posts if not p.date]
    line = f"{C.plural_posts(total)} с датой в этом месяце"
    if no_date:
        line += f" · ещё {len(no_date)} без даты"
    st.caption(line)


def _set_period(year: int, month: int) -> None:
    st.session_state["period"] = (year, month)
    st.session_state["period_note"] = ""
    st.rerun()


# ---------------------------------------------------------------------------
# Вкладка «Посты»
# ---------------------------------------------------------------------------
def _view_posts(data: C.AppData, base, period) -> None:
    # --- KPI-карточки ---
    total = len(base)
    with_issues = sum(1 for _, iss in base if iss)
    cnt = {lvl: sum(1 for _, iss in base for i in iss if i.level == lvl)
           for lvl in _LEVELS}
    sev = st.session_state.get("sev", "all")

    active_css = {
        "all": "kpi_all", "err": "kpi_err", "warn": "kpi_warn", "tip": "kpi_tip",
    }.get(sev)
    if active_css:
        st.markdown(f"<style>.st-key-{active_css} button{{background:#DADFEC;"
                    f"border-color:#1D42A5}}</style>", unsafe_allow_html=True)

    k = st.columns(4)
    if k[0].button(f"Все посты\n\n**{total}**\n\n{with_issues} из них с замечаниями",
                   key="kpi_all", use_container_width=True):
        _set_sev("all")
    if k[1].button(f"Ошибки\n\n**{cnt[Level.ERROR]}**\n\nисправить до публикации",
                   key="kpi_err", use_container_width=True):
        _set_sev("err")
    if k[2].button(f"Предупреждения\n\n**{cnt[Level.WARNING]}**\n\n"
                   f"желательно поправить", key="kpi_warn",
                   use_container_width=True):
        _set_sev("warn")
    tip_sub = "всё в порядке" if cnt[Level.ADVICE] == 0 else "необязательно"
    if k[3].button(f"Советы\n\n**{cnt[Level.ADVICE]}**\n\n{tip_sub}",
                   key="kpi_tip", use_container_width=True):
        _set_sev("tip")

    # --- строка фильтров ---
    brand_codes = list(data.cfg["brands"].keys())
    f = st.columns([6, 4, 3], vertical_alignment="center")
    with f[0]:
        fr = st.columns([1, 5], vertical_alignment="center")
        fr[0].caption("Бренд")
        fr[1].pills("Бренд", ["Все"] + brand_codes, selection_mode="single",
                    key="flt_brand", label_visibility="collapsed")
    with f[1]:
        sr = st.columns([1, 4], vertical_alignment="center")
        sr[0].caption("Статус")
        sr[1].pills("Статус", ["Все", "Готово", "Выложено"],
                    selection_mode="single", key="flt_status",
                    label_visibility="collapsed")
    with f[2]:
        st.toggle("Только с замечаниями", key="flt_only")

    if _filters_active():
        st.button("Сбросить фильтры", on_click=_reset_filters, key="reset_flt")

    # --- список постов (с учётом уровня и «только с замечаниями») ---
    only = st.session_state.get("flt_only", True)
    disp = []
    for p, iss in base:
        if sev in _SEV_LEVEL and not any(i.level == _SEV_LEVEL[sev] for i in iss):
            continue
        if only and not iss:
            continue
        disp.append((p, iss))

    if st.session_state.get("flt_sort") == "Сначала ошибки":
        disp.sort(key=lambda x: (0 if _post_sev(x[1]) == Level.ERROR else 1,
                                 x[0].date or dt.date.max))
    else:
        disp.sort(key=lambda x: (x[0].date or dt.date.max, x[0].sheet, x[0].row))

    if not disp:
        st.success("Постов по выбранным условиям нет")
        _no_date_block(data)
        return

    left, right = st.columns([1.6, 1], gap="medium")
    with left:
        sel_key = _post_list(data, disp)
    with right:
        _post_card(data, dict(((p.sheet, p.row), (p, iss)) for p, iss in disp),
                   sel_key)

    _no_date_block(data)


def _set_sev(code: str) -> None:
    st.session_state["sev"] = code
    st.rerun()


def _filters_active() -> bool:
    return bool(st.session_state.get("flt_brand", "Все") != "Все"
                or st.session_state.get("flt_status", "Все") != "Все"
                or not st.session_state.get("flt_only", True)
                or st.session_state.get("flt_search")
                or st.session_state.get("sev", "all") != "all")


def _reset_filters() -> None:
    st.session_state["flt_brand"] = "Все"
    st.session_state["flt_status"] = "Все"
    st.session_state["flt_only"] = True
    st.session_state["flt_search"] = ""
    st.session_state["sev"] = "all"


def _post_list(data: C.AppData, disp) -> tuple:
    rules = data.cfg["rules"]
    tb = st.columns([3, 5, 4], vertical_alignment="center")
    tb[0].markdown(f"**{C.plural_posts(len(disp))}**")
    tb[1].segmented_control("Сортировка", ["По дате", "Сначала ошибки"],
                            key="flt_sort", label_visibility="collapsed")
    tb[2].text_input("Поиск", key="flt_search", label_visibility="collapsed",
                     placeholder="Поиск по тексту поста")

    verified = st.session_state["verified"]
    rows, sev_colors = [], []
    for p, iss in disp:
        s = _post_sev(iss)
        sev_colors.append(_LVL[s]["dot"] if s else "#858585")
        mark = "✓ " if (p.sheet, p.row) in verified else ""
        rows.append({
            "Замеч.": f"■ {len(iss)}" if iss else "—",
            "Дата": C.fmt_date_compact(p.date) or "без даты",
            "Бренд": p.brand,
            "Рубрика": C.norm_type(p.post_type, rules),
            "Текст поста": mark + _text_preview(p, 90),
        })
    df = pd.DataFrame(rows)
    styler = df.style.apply(
        lambda col: [f"color:{c};font-weight:600" for c in sev_colors],
        subset=["Замеч."])
    event = st.dataframe(
        styler, use_container_width=True, hide_index=True, height=520,
        on_select="rerun", selection_mode="single-row",
        column_config={
            "Замеч.": st.column_config.TextColumn(width="small"),
            "Дата": st.column_config.TextColumn(width="small"),
            "Бренд": st.column_config.TextColumn(width="small"),
            "Рубрика": st.column_config.TextColumn(width="medium"),
            "Текст поста": st.column_config.TextColumn(width="large"),
        })

    keys = [(p.sheet, p.row) for p, _ in disp]
    sel_rows = event.selection.rows if event and event.selection else []
    if sel_rows:
        st.session_state["sel_post"] = keys[sel_rows[0]]

    cur = st.session_state.get("sel_post")
    if cur not in keys:
        # по умолчанию — первый пост с ошибкой, иначе первый
        cur = next((keys[i] for i, (_, iss) in enumerate(disp)
                    if _post_sev(iss) == Level.ERROR), keys[0])
        st.session_state["sel_post"] = cur
    return cur


# ---------------------------------------------------------------------------
# Карточка поста
# ---------------------------------------------------------------------------
def _post_card(data: C.AppData, by_key: dict, sel_key: tuple) -> None:
    post, issues = by_key[sel_key]
    rules = data.cfg["rules"]
    verified = st.session_state["verified"]

    with st.container(border=True):
        rubric = C.norm_type(post.post_type, rules)
        meta = " · ".join(x for x in (C.fmt_date_compact(post.date) or "без даты",
                                      post.brand, rubric) if x)
        if post.date_note:
            meta += f" · {post.date_note}"
        st.caption(meta)
        st.markdown(f"**{_text_preview(post, 80)}**")

        # полный текст поста на сером фоне (прокручивается)
        excerpt = html.escape((post.text or "").strip()) or "(текст не заполнен)"
        st.markdown(
            f'<div style="padding:12px 14px;background:#F3F3F3;border-radius:4px;'
            f'font-size:14px;line-height:22px;white-space:pre-wrap;'
            f'max-height:360px;overflow:auto">{excerpt}</div>',
            unsafe_allow_html=True)

        # орфография для выбранного поста (кешируется)
        all_issues = issues + _spell_issues(data, post)
        order = {Level.ERROR: 0, Level.WARNING: 1, Level.ADVICE: 2, Level.TECH: 3}
        all_issues = sorted(all_issues, key=lambda i: order.get(i.level, 9))

        st.markdown(f"**Замечания · {len(all_issues)}**")
        if not all_issues:
            st.success("Замечаний нет")
        for n, iss in enumerate(all_issues):
            _issue_block(post, iss, n)

        # фото
        _photos(post)

        # кнопки
        st.write("")
        cols = st.columns(2)
        link = C.sheet_link(post.row, post.sheet)
        if link:
            cols[0].link_button("Открыть в таблице", link,
                                use_container_width=True)
        is_done = sel_key in verified
        label = "Снять отметку" if is_done else "Отметить проверенным"
        if cols[1].button(label, key="mark_done", use_container_width=True,
                          type="secondary" if is_done else "primary"):
            if is_done:
                verified.discard(sel_key)
            else:
                verified.add(sel_key)
            st.rerun()


def _issue_block(post: PostRecord, iss: Issue, n: int) -> None:
    with st.container(border=True):
        name = _rule_name(iss.code, iss.message)
        st.markdown(f'{_tag(iss.level)}&nbsp; <b>{html.escape(name)}</b>',
                    unsafe_allow_html=True)
        # что именно не так — конкретика из проверки
        if iss.message:
            st.markdown(f'<span style="color:#464646;font-size:14px">'
                        f'{html.escape(iss.message)}</span>',
                        unsafe_allow_html=True)
        # как исправить — если добавляет новое к сообщению
        fix = (iss.fix or "").strip()
        if fix and fix not in (iss.message or ""):
            st.markdown(f'<span style="color:#464646;font-size:13px">'
                        f'Как исправить: {html.escape(fix)}</span>',
                        unsafe_allow_html=True)
        frag = _fragment_for_issue(iss)
        frag_html = _frag_html(post.text or "", frag) if frag else None
        if frag_html:
            st.markdown(f'<span style="font-size:14px">Фрагмент: {frag_html}'
                        f'</span>', unsafe_allow_html=True)
        # действия (сохранены прежние возможности)
        if iss.code == "spell_error":
            if st.button("Добавить слово",
                         key=f"wl_{post.sheet}_{post.row}_{n}",
                         type="tertiary", help="Добавить в словарь орфографии"):
                config_mod.add_word_to_whitelist(iss.extra.get("word", ""))
                C.persist_all()
                st.rerun()
        else:
            if st.button("Не ошибка", key=f"ig_{post.sheet}_{post.row}_{n}",
                         type="tertiary", help="Скрыть это замечание"):
                chash = config_mod.content_hash(post.text)
                config_mod.add_ignored(iss.sheet, iss.code, chash, row=post.row)
                C.persist_all()
                st.rerun()


def _frag_html(text: str, frag: str, words: int = 3):
    """Показать фрагмент с парой слов до и после — понятно, где это в тексте."""
    idx = (text or "").find(frag)
    if idx == -1:
        return None
    before = text[:idx].split()
    after = text[idx + len(frag):].split()
    pre = " ".join(before[-words:])
    post_ = " ".join(after[:words])
    lead = "…" if len(before) > words else ""
    tail = "…" if len(after) > words else ""
    mark = (f'<mark style="background:#FFE26C;color:#1E1E1E;padding:0 3px;'
            f'border-radius:2px">{html.escape(frag)}</mark>')
    return (f'{lead}{html.escape(pre)} {mark} {html.escape(post_)}{tail}').strip()


def _fragment_for_issue(iss: Issue):
    m = re.search(r"«([^»]+)»", iss.message)
    if m:
        return m.group(1)
    m = re.search(r"\[[^\]]+\]", iss.message)
    if m:
        return m.group(0)
    m = re.search(r"#[\wА-Яа-яЁё]+", iss.message)
    if m:
        return m.group(0)
    return None


# ---------------------------------------------------------------------------
# Орфография
# ---------------------------------------------------------------------------
def _spell_issues(data: C.AppData, post: PostRecord) -> list[Issue]:
    if not (post.text or "").strip():
        return []
    status, words = C.spell_for_post(post, data.cfg)
    if status == "unavailable":
        return []
    out = []
    for w in words:
        variants = ", ".join(w["variants"]) or "нет вариантов"
        out.append(Issue(post.sheet, post.row, "Пост", Level.WARNING,
                         "spell_error",
                         f"Возможная опечатка: «{w['word']}». Варианты: {variants}.",
                         "Проверьте слово или добавьте его в словарь.",
                         brand=post.brand, extra={"word": w["word"]}))
    return out


@st.fragment
def _spell_all_fragment(data: C.AppData, base) -> None:
    posts = [p for p, _ in base if (p.text or "").strip()]
    total = len(posts) or 1
    with st.status("Проверяем орфографию…", expanded=True) as status:
        unavailable = False
        found = 0
        for n, p in enumerate(posts, 1):
            st_, words = C.spell_for_post(p, data.cfg)
            if st_ == "unavailable":
                unavailable = True
                break
            found += len(words)
            status.update(label=f"Проверено {n} из {total}…")
        if unavailable:
            status.update(label="Орфографию проверить не удалось, нет связи "
                          "с сервисом.", state="error")
        else:
            status.update(label=f"Готово. Слов с возможными опечатками: {found}.",
                          state="complete")


# ---------------------------------------------------------------------------
# Фото
# ---------------------------------------------------------------------------
_PHOTO_TAG_RE = re.compile(r"^(ЛОГО|БЕЗ ЛОГО|ЯБ|СОЦ)\s*:\s*", re.IGNORECASE)


def _photo_parts(ph: str, i: int) -> tuple[str, str, str]:
    m = _PHOTO_TAG_RE.match(ph)
    tag = m.group(1).upper() if m else ""
    direct = _PHOTO_TAG_RE.sub("", ph).strip()
    caption = tag or f"Фото {i}"
    button = f"Фото {i}" + (f" ({tag})" if tag else "")
    return caption, button, direct


def _photos(post: PostRecord) -> None:
    if not post.photos:
        return
    items = [_photo_parts(ph, i) for i, ph in enumerate(post.photos, 1)]
    per_row = 4
    for start in range(0, len(items), per_row):
        chunk = items[start:start + per_row]
        cols = st.columns(per_row)
        for col, (caption, button, direct) in zip(cols, chunk):
            with col:
                is_img = bool(re.match(r"https?://i\.ibb\.co/", direct)) or (
                    direct.lower().startswith("http")
                    and re.search(r"\.(jpg|jpeg|png|gif|webp)(\?|$)",
                                  direct, re.IGNORECASE))
                if is_img:
                    st.image(direct, use_container_width=True, caption=caption)
                elif direct.lower().startswith("http"):
                    st.link_button(button, direct, use_container_width=True)
                else:
                    st.caption((direct or caption)[:40])


# ---------------------------------------------------------------------------
# Посты без даты
# ---------------------------------------------------------------------------
def _no_date_block(data: C.AppData) -> None:
    brand_sel = st.session_state.get("flt_brand") or "Все"
    no_date = [p for p in data.posts if not p.date
               and (brand_sel == "Все" or p.brand == brand_sel)]
    if not no_date:
        return
    st.divider()
    st.markdown(f"##### Посты без даты · {C.plural_posts(len(no_date))}")
    st.caption("У этих постов не заполнена дата — они не попадают ни в один "
               "месяц. Проставьте дату в таблице.")
    rules = data.cfg["rules"]
    rows = [{"Лист": p.sheet, "Строка": p.row, "Бренд": p.brand,
             "Рубрика": C.norm_type(p.post_type, rules),
             "Начало текста": _text_preview(p, 90)} for p in no_date]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                 height=min(360, 60 + 35 * len(rows)),
                 column_config={"Начало текста":
                                st.column_config.TextColumn(width="large")})


# ---------------------------------------------------------------------------
# Вкладка «Календарь»
# ---------------------------------------------------------------------------
def _view_calendar(data: C.AppData, base, period) -> None:
    today = C.moscow_today()
    year, month = period if isinstance(period, tuple) else (today.year, today.month)
    brand_codes = list(data.cfg["brands"].keys())
    rules = data.cfg["rules"]

    total = len(base)
    with_issues = sum(1 for _, iss in base if iss)
    cnt = {lvl: sum(1 for _, iss in base for i in iss if i.level == lvl)
           for lvl in _LEVELS}

    bar = st.columns([6, 3], vertical_alignment="center")
    with bar[0]:
        st.markdown(
            f'<div style="display:flex;gap:20px;align-items:center;flex-wrap:wrap;'
            f'padding:10px 14px;border:1px solid #DFDFDF;border-radius:4px;'
            f'font-size:14px"><span><b>{total}</b> постов · '
            f'<b>{with_issues}</b> с замечаниями</span>'
            f'<span>{_square(_LVL[Level.ERROR]["dot"])}<b>{cnt[Level.ERROR]}</b>'
            f' ошибок</span>'
            f'<span>{_square(_LVL[Level.WARNING]["dot"])}'
            f'<b>{cnt[Level.WARNING]}</b> предупреждений</span>'
            f'<span>{_square(_LVL[Level.ADVICE]["dot"])}<b>{cnt[Level.ADVICE]}</b>'
            f' советов</span></div>', unsafe_allow_html=True)
    with bar[1]:
        st.pills("Бренд", ["Все"] + brand_codes, selection_mode="single",
                 key="flt_brand", label_visibility="collapsed")

    by_day: dict[int, list] = {}
    for p, iss in base:
        by_day.setdefault(p.date.day, []).append((p, iss))

    days_with = sorted(by_day.keys())
    cur = st.session_state.get("cal_day")
    if cur not in by_day:
        if (today.year, today.month) == (year, month) and today.day in by_day:
            cur = today.day
        else:
            cur = days_with[0] if days_with else None
        st.session_state["cal_day"] = cur

    grid, aside = st.columns([2, 1], gap="medium")
    with grid:
        head = st.columns(7)
        for i, wd in enumerate(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]):
            head[i].caption(wd)
        for week in _cal.monthcalendar(year, month):
            cols = st.columns(7)
            for i, dnum in enumerate(week):
                if dnum == 0:
                    cols[i].markdown("&nbsp;", unsafe_allow_html=True)
                    continue
                _cal_cell(cols[i], dnum, by_day.get(dnum, []), rules,
                          selected=(dnum == cur))
    with aside:
        _cal_aside(data, year, month, cur, by_day, rules)


def _cal_cell(col, dnum: int, items, rules, selected: bool) -> None:
    if col.button(str(dnum), key=f"cal_{dnum}", use_container_width=True,
                  type="primary" if selected else "secondary"):
        st.session_state["cal_day"] = dnum
        st.rerun()
    chips = ""
    for p, iss in items[:3]:
        s = _post_sev(iss)
        dot = _square(_LVL[s]["dot"] if s else "#858585", 8)
        ptype = html.escape(C.norm_type(p.post_type, rules))
        chips += (f'<div style="display:flex;align-items:flex-start;gap:4px;'
                  f'padding:2px 5px;border:1px solid #DFDFDF;border-radius:4px;'
                  f'font-size:11px;line-height:15px;margin-bottom:3px;'
                  f'text-align:left">{dot}<span><b>{html.escape(p.brand)}</b> '
                  f'{ptype}</span></div>')
    extra = len(items) - 3
    if extra > 0:
        chips += f'<div style="font-size:11px;color:#464646">+{extra}</div>'
    if chips:
        col.markdown(chips, unsafe_allow_html=True)


def _cal_aside(data: C.AppData, year: int, month: int, day, by_day, rules) -> None:
    if day:
        items = by_day.get(day, [])
        n_iss = sum(len(iss) for _, iss in items)
        d = dt.date(year, month, day)
        with st.container(border=True):
            st.markdown(f"**{d.day} {C.MONTHS_GEN[d.month]}, "
                        f"{C.WEEKDAYS_FULL[d.weekday()]}**")
            st.caption(f"{C.plural_posts(len(items))} · {n_iss} замечаний")
            for p, iss in items:
                s = _post_sev(iss)
                dot = _square(_LVL[s]["dot"] if s else "#858585", 8)
                with st.container(border=True):
                    st.markdown(f'{dot}<b>{html.escape(p.brand)}</b> · '
                                f'{html.escape(C.norm_type(p.post_type, rules))}',
                                unsafe_allow_html=True)
                    st.markdown(f'<span style="font-size:14px">'
                                f'{html.escape(_text_preview(p, 70))}</span>',
                                unsafe_allow_html=True)
                    if iss:
                        st.caption(" · ".join(_rule_name(i.code, i.message)
                                              for i in iss[:3]))
                    if st.button("Открыть", key=f"calopen_{p.sheet}_{p.row}",
                                 type="tertiary"):
                        st.session_state["sel_post"] = (p.sheet, p.row)
                        st.session_state["force_view"] = "Посты"
                        st.rerun()

    brand_sel = st.session_state.get("flt_brand") or "Все"
    no_date = [p for p in data.posts if not p.date
               and (brand_sel == "Все" or p.brand == brand_sel)]
    with st.container(border=True):
        st.markdown(f"**Без даты · {C.plural_posts(len(no_date))}**")
        st.caption("Их нет в календаре, пока в таблице не указана дата публикации.")


# ---------------------------------------------------------------------------
# Вкладка «Замечания» (по типам)
# ---------------------------------------------------------------------------
def _view_issues(data: C.AppData, base, period) -> None:
    brand_codes = list(data.cfg["brands"].keys())
    st.pills("Бренд", ["Все"] + brand_codes, selection_mode="single",
             key="flt_brand", label_visibility="collapsed")

    # сгруппировать структурные замечания по коду и уровню
    by_key = dict(((p.sheet, p.row), (p, iss)) for p, iss in base)
    groups: dict[Level, dict[str, list[tuple]]] = {l: {} for l in _LEVELS}
    for p, iss in base:
        for i in iss:
            if i.level not in groups:
                continue
            groups[i.level].setdefault(i.code, []).append((p, i))

    # выбранное правило: идентификатор = «уровень|код» (один код бывает на
    # разных уровнях, напр. хештег обязателен в «Отгрузке» и желателен иначе)
    all_ids = [f"{lvl.value}|{code}" for lvl in _LEVELS for code in groups[lvl]]
    sel_rule = st.session_state.get("sel_rule")
    if sel_rule not in all_ids:
        sel_rule = all_ids[0] if all_ids else None
        st.session_state["sel_rule"] = sel_rule

    total_issues = sum(len(v) for lvl in _LEVELS for v in groups[lvl].values())
    posts_with = len({k for k, (_, iss) in by_key.items() if iss})
    st.caption(f"{total_issues} замечаний в {posts_with} постах из {len(base)}")

    if not all_ids:
        st.success("Замечаний по выбранным условиям нет")
        return

    left, right = st.columns([1.1, 2], gap="medium")
    with left:
        for lvl in _LEVELS:
            rules_map = groups[lvl]
            if not rules_map:
                continue
            d = _LVL[lvl]
            total = sum(len(v) for v in rules_map.values())
            st.markdown(f'{_square(d["dot"])}<b>{d["plural"]} · {total}</b>',
                        unsafe_allow_html=True)
            ordered = sorted(rules_map.items(), key=lambda kv: -len(kv[1]))
            for code, items in ordered:
                rid = f"{lvl.value}|{code}"
                n_posts = len({(p.sheet, p.row) for p, _ in items})
                active = rid == sel_rule
                if st.button(f"{_rule_name(code, items[0][1].message)} · {n_posts}",
                             key=f"rule_{rid}", use_container_width=True,
                             type="primary" if active else "secondary"):
                    st.session_state["sel_rule"] = rid
                    st.rerun()
            st.write("")

    with right:
        _rule_detail(data, groups, sel_rule)


def _rule_detail(data: C.AppData, groups, rule_id: str) -> None:
    level_val, _, code = rule_id.partition("|")
    level = Level(level_val)
    items = groups[level][code]
    verified = st.session_state["verified"]

    # уникальные посты
    seen, posts = set(), []
    for p, i in items:
        key = (p.sheet, p.row)
        if key not in seen:
            seen.add(key)
            posts.append((p, i))
    total = len(posts)
    done = sum(1 for p, _ in posts if (p.sheet, p.row) in verified)

    with st.container(border=True):
        st.markdown(f'{_tag(level)}&nbsp; '
                    f'<b style="font-size:18px">{html.escape(_rule_name(code))}</b>',
                    unsafe_allow_html=True)
        hint = items[0][1].fix or ""
        st.markdown(f'<span style="color:#464646">{html.escape(hint)}</span> '
                    'Отметьте пост, когда исправите его в таблице — отметка '
                    'сохранится до обновления данных.', unsafe_allow_html=True)
        st.progress(done / total if total else 0.0,
                    text=f"Исправлено {done} из {total}")

        st.write("")
        for p, i in posts:
            key = (p.sheet, p.row)
            row = st.columns([1, 3, 2, 8, 3], vertical_alignment="center")
            checked = row[0].checkbox(
                "исправлено", value=key in verified,
                key=f"chk_{level_val}_{code}_{p.sheet}_{p.row}",
                label_visibility="collapsed")
            if checked:
                verified.add(key)
            else:
                verified.discard(key)
            muted = "color:#858585;" if key in verified else ""
            strike = "text-decoration:line-through;" if key in verified else ""
            row[1].markdown(f'<span style="{muted}">'
                            f'{C.fmt_date_compact(p.date) or "—"}</span>',
                            unsafe_allow_html=True)
            row[2].markdown(f'<span style="font-weight:600;{muted}">{p.brand}'
                            f'</span>', unsafe_allow_html=True)
            row[3].markdown(
                f'<span style="{muted}{strike}white-space:nowrap;overflow:hidden;'
                f'text-overflow:ellipsis;display:block">'
                f'{html.escape(_text_preview(p, 80))}</span>',
                unsafe_allow_html=True)
            if row[4].button("Открыть",
                             key=f"open_{level_val}_{code}_{p.sheet}_{p.row}",
                             type="tertiary"):
                st.session_state["sel_post"] = key
                st.session_state["force_view"] = "Посты"
                st.rerun()
