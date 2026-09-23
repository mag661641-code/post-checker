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
import time

import pandas as pd
import streamlit as st

from checker import config_mod
from checker import ai_review as ai_review_mod
from checker import text_checks
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

# короткие названия типов постов для тесных мест (ячейки календаря)
_TYPE_SHORT = {
    "Отгрузка": "Отгрузка", "Спецпредложение": "Спецпредл.",
    "Поступление": "Поступл.", "Информационный": "Информ.",
    "Праздник": "Праздник", "Поздравление": "Поздравл.",
    "Поздравление (сотрудники)": "Поздр.(сотр.)",
    "Развлекательный": "Развлек.", "Дзен": "Дзен", "Анонс": "Анонс",
}


def _short_type(name: str) -> str:
    n = (name or "").strip()
    if n in _TYPE_SHORT:
        return _TYPE_SHORT[n]
    return (n[:9] + ".") if len(n) > 10 else n

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
    C.sync_ai_res_from_cache(data)  # восстановить сохранённые проверки нейросети
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

    # --- отдельный экран поста: проверка текста нейросетью ---
    ai_key = st.session_state.get("ai_post")
    if ai_key:
        post = next((p for p in data.posts if (p.sheet, p.row) == ai_key), None)
        if post is not None:
            _ai_page(data, post, period)
            return
        st.session_state.pop("ai_post", None)

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
    # --- массовая проверка нейросетью + счётчик ---
    _ai_bulk_bar(data, base)

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

        # смысловая проверка нейросетью — на отдельном экране
        st.divider()
        st.markdown("**Замечания нейросети** 🤖")
        if C.get_ai_key():
            n_ai = _ai_pending_count(sel_key)
            hint = f" · {n_ai} на рассмотрении" if n_ai else ""
            if st.button(f"🤖 Проверить текст нейросетью{hint}",
                         key=f"open_ai_{post.sheet}_{post.row}",
                         use_container_width=True, type="secondary"):
                st.session_state["ai_post"] = sel_key
                st.rerun()
            st.caption("Откроется отдельный экран: советы по тону и стилю с "
                       "готовыми вариантами замены. Это платный запрос к Google AI.")
        else:
            st.button("🤖 Проверить текст нейросетью", disabled=True,
                      key=f"open_ai_{post.sheet}_{post.row}",
                      use_container_width=True)
            st.caption("Добавьте ключ Google AI, чтобы включить проверку.")

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


# ---------------------------------------------------------------------------
# Смысловая проверка нейросетью (🤖) — отдельный экран поста
# ---------------------------------------------------------------------------
def _ai_decisions(key: tuple) -> dict:
    """Решения по замечаниям поста: индекс замечания -> {status, text}."""
    return st.session_state.setdefault("ai_dec", {}).setdefault(key, {})


def _ai_pending_count(key: tuple) -> int:
    entry = st.session_state.get("ai_res", {}).get(key)
    if not entry or not entry["res"].get("ok"):
        return 0
    issues = entry["res"].get("issues", [])
    dec = st.session_state.get("ai_dec", {}).get(key, {})
    return sum(1 for i in range(len(issues))
               if dec.get(i, {}).get("status") not in ("accepted", "rejected"))


def _ai_done(store: dict, post: PostRecord) -> bool:
    """Пост уже успешно проверен нейросетью и текст с тех пор не менялся."""
    e = store.get((post.sheet, post.row))
    return bool(e and e["res"].get("ok")
                and e["hash"] == config_mod.content_hash(post.text))


def _ai_bulk_bar(data: C.AppData, base) -> None:
    """Счётчик проверенных постов + кнопка «Проверить все нейросетью»."""
    if not C.get_ai_key():
        return
    posts = [p for p, _ in base if (p.text or "").strip()]
    total = len(posts)
    if not total:
        return
    store = st.session_state.setdefault("ai_res", {})
    done = sum(1 for p in posts if _ai_done(store, p))

    row = st.columns([6, 3], vertical_alignment="center")
    row[0].caption(f"🤖 Нейросеть: проверено {done} из {total} постов выборки")
    left = total - done
    label = ("Все посты проверены" if left == 0
             else f"🤖 Проверить остальные ({left})")
    if row[1].button(label, key="ai_bulk_open", use_container_width=True,
                     disabled=(left == 0)):
        st.session_state["ai_bulk_confirm"] = True
        st.rerun()

    if st.session_state.get("ai_bulk_confirm"):
        with st.container(border=True):
            st.warning(f"Проверить нейросетью {left} "
                       f"{C.plural(left, 'пост', 'поста', 'постов')}? "
                       "Это платные запросы к Google AI — по одному на пост.")
            cc = st.columns([2, 2, 5])
            if cc[0].button("Да, проверить", type="primary", key="ai_bulk_go"):
                st.session_state["ai_bulk_confirm"] = False
                st.session_state["ai_bulk_go_run"] = True
                st.rerun()
            if cc[1].button("Отмена", key="ai_bulk_cancel"):
                st.session_state["ai_bulk_confirm"] = False
                st.rerun()

    if st.session_state.get("ai_bulk_go_run"):
        st.session_state["ai_bulk_go_run"] = False
        _ai_bulk_run(data, posts)


def _ai_bulk_run(data: C.AppData, posts) -> None:
    store = st.session_state.setdefault("ai_res", {})
    pending = [p for p in posts if not _ai_done(store, p)]
    if not pending:
        st.success("Все посты уже проверены.")
        return
    pause = float(ai_review_mod.ai_settings(data.cfg["rules"])
                  .get("pause_seconds", 1.0) or 0)
    ok = err = 0
    with st.status(f"Проверяю нейросетью… 0 из {len(pending)}",
                   expanded=True) as status:
        for n, p in enumerate(pending, 1):
            res = C.ai_review_post(data, p)
            store[(p.sheet, p.row)] = {
                "hash": config_mod.content_hash(p.text), "res": res}
            if res.get("ok"):
                ok += 1
            else:
                err += 1
                status.write(f"⚠️ {p.brand}, строка {p.row}: "
                             f"{res.get('error', '')}")
            status.update(label=f"Проверяю нейросетью… {n} из {len(pending)}")
            if pause and n < len(pending):
                time.sleep(pause)
        st.session_state["ai_checked_count"] = \
            st.session_state.get("ai_checked_count", 0) + ok
        state = "complete" if err == 0 else "error"
        status.update(state=state,
                      label=f"Готово. Проверено {ok}"
                            + (f", с ошибкой {err}" if err else "") + ".")
    if ok:
        C.persist_ai_cache()  # сохранить, чтобы после перезагрузки не платить


def _ai_page(data: C.AppData, post: PostRecord, period) -> None:
    rules = data.cfg["rules"]
    key = (post.sheet, post.row)
    today = C.moscow_today()
    year, month = period if isinstance(period, tuple) else (today.year, today.month)

    if st.button(f"← Все посты · {C.MONTHS_NOM[month].lower()} {year}",
                 key="ai_back", type="tertiary"):
        st.session_state.pop("ai_post", None)
        st.rerun()

    rubric = C.norm_type(post.post_type, rules)
    meta = " · ".join(x for x in (C.fmt_date_compact(post.date) or "без даты",
                                  post.brand, rubric) if x)

    # пост, где в ячейке по сути только ссылка на документ/статью
    only = text_checks._content_only_link(post)
    is_external = bool(only and only[0] in ("gdoc", "dzen"))
    ext_store = st.session_state.setdefault("ai_ext_text", {})
    review_text = ext_store.get(key, post.text)

    store = st.session_state.setdefault("ai_res", {})
    entry = store.get(key)
    chash = config_mod.content_hash(review_text)

    top = st.columns([6, 3, 3], vertical_alignment="center")
    top[0].markdown(f"### {meta}")
    link = C.sheet_link(post.row, post.sheet)
    if link:
        top[1].link_button("Открыть в таблице", link, use_container_width=True)

    need_fetch = is_external and key not in ext_store
    if need_fetch:
        run_label = "🤖 Загрузить текст и проверить"
    else:
        run_label = "Проверить заново" if entry else "🤖 Проверить нейросетью"

    if top[2].button(run_label, key="ai_run", type="primary",
                     use_container_width=True):
        text_for_review, fetch_err = review_text, None
        if need_fetch:
            with st.spinner("Загружаю текст по ссылке…"):
                fetched, _kind, fetch_err = C.fetch_post_link_text(post)
            if not fetch_err:
                ext_store[key] = fetched
                text_for_review = fetched
        if fetch_err:
            st.error(fetch_err)  # без rerun — чтобы сообщение осталось
        else:
            with st.spinner("Проверяем нейросетью…"):
                res = C.ai_review_post(data, post, text_override=text_for_review)
            store[key] = {"hash": config_mod.content_hash(text_for_review),
                          "res": res}
            st.session_state.setdefault("ai_dec", {})[key] = {}  # сброс решений
            if res.get("ok"):
                st.session_state["ai_checked_count"] = \
                    st.session_state.get("ai_checked_count", 0) + 1
                C.persist_ai_cache()
            st.rerun()

    # пояснение для постов-ссылок
    if is_external:
        if only[0] == "gdoc":
            st.caption("📄 Текст поста — в Google Документе. Сервис прочитает его "
                       "по ссылке, если документ доступен сервисному аккаунту "
                       "или открыт по ссылке.")
        else:
            st.caption("📄 Текст поста — статья в Дзене. Сервис попробует "
                       "прочитать её по ссылке (получается не всегда).")

    entry = store.get(key)
    if not entry:
        if not is_external:
            st.info("Нажмите «Проверить нейросетью» — сервис пришлёт советы по "
                    "тону и стилю с готовыми вариантами замены. Факты, цифры, "
                    "ГОСТы и контакты нейросеть не трогает, а в таблицу ничего "
                    "не пишет.")
        return
    res = entry["res"]
    if not res.get("ok"):
        st.error("Проверка нейросетью не выполнена: " + res.get("error", ""))
        return
    if entry["hash"] != chash:
        st.warning("⚠️ Текст изменился после проверки — нажмите «Проверить "
                   "заново».")

    issues = res.get("issues", [])
    left, right = st.columns([1.4, 1], gap="large")
    with left:
        _ai_cards(post, key, issues)
    with right:
        _ai_preview(post, key, issues, review_text)


def _ai_cards(post: PostRecord, key: tuple, issues: list[dict]) -> None:
    dec = _ai_decisions(key)
    acc = sum(1 for i in range(len(issues))
              if dec.get(i, {}).get("status") == "accepted")
    rej = sum(1 for i in range(len(issues))
              if dec.get(i, {}).get("status") == "rejected")
    pend = len(issues) - acc - rej

    st.markdown("#### Замечания нейросети")
    st.markdown(f'<span style="font-size:14px"><b>{pend}</b> ждут решения '
                f'<span style="color:#464646">· {acc} принято · {rej} отклонено'
                f'</span></span>', unsafe_allow_html=True)

    if not issues:
        st.success("Нейросеть замечаний не нашла.")
        return
    for i, item in enumerate(issues):
        _ai_card(post, key, item, i)
    st.caption("Нейросеть может ошибаться. Факты, цифры и сроки проверяйте "
               "с отделом продаж.")


def _ai_card(post: PostRecord, key: tuple, item: dict, i: int) -> None:
    dec = _ai_decisions(key)
    status = dec.get(i, {}).get("status", "pending")
    title = html.escape(item.get("title", ""))
    frag = item.get("fragment", "")
    uid = f"{key[0]}_{key[1]}_{i}"

    # принято / отклонено — компактная строка
    if status == "accepted":
        applied = dec[i].get("text", "")
        with st.container(border=True):
            row = st.columns([8, 2], vertical_alignment="center")
            short = _clip(f"«{frag}» → «{applied}»", 80)
            row[0].markdown(f'<span style="color:#107C10;font-weight:600">'
                            f'✓ Принято</span> <span style="color:#464646">'
                            f'{title}:</span> {html.escape(short)}',
                            unsafe_allow_html=True)
            if row[1].button("Отменить", key=f"ai_undo_{uid}", type="tertiary"):
                dec.pop(i, None)
                st.rerun()
        return
    if status == "rejected":
        with st.container(border=True):
            row = st.columns([8, 2], vertical_alignment="center")
            row[0].markdown(f'<span style="color:#464646;font-weight:600">'
                            f'Отклонено</span> <span style="color:#464646">'
                            f'{title}</span>', unsafe_allow_html=True)
            if row[1].button("Вернуть", key=f"ai_back_{uid}", type="tertiary"):
                dec.pop(i, None)
                st.rerun()
        return

    # ждёт решения
    lvl = Level.WARNING if item.get("level") == "warning" else Level.ADVICE
    options = item.get("options", [])
    with st.container(border=True):
        st.markdown(f'🤖 {_tag(lvl)}&nbsp; <b>{title}</b>',
                    unsafe_allow_html=True)
        if item.get("why"):
            st.markdown(f'<span style="color:#464646;font-size:14px">'
                        f'{html.escape(item["why"])}</span>',
                        unsafe_allow_html=True)
        if frag:
            st.markdown('<span style="font-size:12px;font-weight:600;'
                        'color:#464646">Сейчас в тексте</span>',
                        unsafe_allow_html=True)
            st.markdown(f'<div style="padding:8px 12px;background:#EBD7D7;'
                        f'border-radius:4px;font-size:14px;line-height:20px">'
                        f'{html.escape(frag)}</div>', unsafe_allow_html=True)

        chosen = None
        if options:
            st.markdown('<span style="font-size:12px;font-weight:600;'
                        'color:#464646">Заменить на</span>',
                        unsafe_allow_html=True)
            custom_on = st.toggle("Свой вариант", key=f"ai_custon_{uid}")
            if custom_on:
                custom = st.text_area(
                    "Свой вариант замены", key=f"ai_cust_{uid}",
                    label_visibility="collapsed",
                    placeholder="Впишите свой вариант замены фрагмента")
                chosen = (custom or "").strip()
            elif len(options) == 1:
                chosen = options[0]["text"]
                st.markdown(f'<div style="padding:8px 12px;background:#DADFEC;'
                            f'border:1px solid #1D42A5;border-radius:4px;'
                            f'font-size:14px;line-height:20px">'
                            f'{html.escape(chosen)}</div>',
                            unsafe_allow_html=True)
            else:
                labels = [((o["when"] + ": ") if o.get("when") else "")
                          + o["text"] for o in options]
                pick = st.radio("Вариант замены", list(range(len(options))),
                                format_func=lambda k: labels[k],
                                key=f"ai_opt_{uid}", label_visibility="collapsed")
                chosen = options[pick]["text"]

            b = st.columns([2, 2, 3], vertical_alignment="center")
            if b[0].button("Заменить", key=f"ai_acc_{uid}", type="primary",
                           use_container_width=True):
                if chosen:
                    dec[i] = {"status": "accepted", "text": chosen}
                    st.rerun()
                else:
                    st.warning("Впишите вариант замены.")
            if b[1].button("Отклонить", key=f"ai_rej_{uid}",
                           use_container_width=True):
                dec[i] = {"status": "rejected"}
                st.rerun()
        else:
            # совет без готовой замены (в т.ч. факт/обещание) — только скрыть
            if st.button("Понятно, скрыть", key=f"ai_hide_{uid}",
                         type="tertiary"):
                dec[i] = {"status": "rejected"}
                st.rerun()


def _clip(s: str, limit: int) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= limit else s[:limit].rstrip() + "…"


def _apply_repl(text: str, repl: list[dict]) -> tuple[str, str]:
    """Разбить текст на сегменты, применяя замены по очереди.

    Возвращает (html-предпросмотр с подсветкой, итоговый обычный текст).
    """
    segs = [{"t": text or "", "kind": ""}]
    for r in repl:
        new, placed = [], False
        for g in segs:
            if placed or g["kind"] or r["from"] not in g["t"]:
                new.append(g)
                continue
            idx = g["t"].index(r["from"])
            before, after = g["t"][:idx], g["t"][idx + len(r["from"]):]
            if before:
                new.append({"t": before, "kind": ""})
            if r["accepted"]:
                new.append({"t": r["to"], "kind": "done"})
            else:
                new.append({"t": r["from"], "kind": "pending"})
            if after:
                new.append({"t": after, "kind": ""})
            placed = True
        segs = new

    parts, plain = [], []
    for g in segs:
        esc = html.escape(g["t"])
        if g["kind"] == "pending":
            parts.append(f'<mark style="background:#FFE26C;color:#1E1E1E;'
                         f'border-radius:2px">{esc}</mark>')
        elif g["kind"] == "done":
            parts.append(f'<mark style="background:#DADFEC;color:#1E1E1E;'
                         f'box-shadow:inset 0 -1px 0 #1D42A5;'
                         f'border-radius:2px">{esc}</mark>')
        else:
            parts.append(esc)
        plain.append(g["t"])
    return "".join(parts), "".join(plain)


def _ai_preview(post: PostRecord, key: tuple, issues: list[dict],
                text: str) -> None:
    dec = _ai_decisions(key)
    repl = []
    for i, item in enumerate(issues):
        frag = item.get("fragment", "")
        status = dec.get(i, {}).get("status", "pending")
        if not frag or status == "rejected":
            continue
        repl.append({"from": frag,
                     "to": dec[i]["text"] if status == "accepted" else frag,
                     "accepted": status == "accepted"})

    html_preview, final_text = _apply_repl(text or "", repl)

    st.markdown("#### Текст поста")
    st.markdown(
        '<span style="font-size:12px;color:#464646">'
        '<span style="background:#FFE26C;border-radius:2px;padding:0 4px">'
        '&nbsp;</span> к замене &nbsp;&nbsp;'
        '<span style="background:#DADFEC;border-radius:2px;padding:0 4px;'
        'box-shadow:inset 0 -1px 0 #1D42A5">&nbsp;</span> заменено</span>',
        unsafe_allow_html=True)
    st.markdown(
        f'<div style="padding:14px 16px;border:1px solid #DFDFDF;'
        f'border-radius:4px;font-size:14px;line-height:22px;white-space:pre-wrap;'
        f'max-height:520px;overflow:auto">{html_preview or "(текст не заполнен)"}'
        f'</div>', unsafe_allow_html=True)
    st.caption("Так пост будет выглядеть после принятых замен. Текст в таблице "
               "сам не меняется.")
    st.markdown("**Итоговый текст** — скопируйте кнопкой в правом углу поля:")
    st.code(final_text or "", language=None)


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
        ptype = html.escape(_short_type(C.norm_type(p.post_type, rules)))
        chips += (f'<div style="display:flex;align-items:center;gap:4px;'
                  f'padding:2px 5px;border:1px solid #DFDFDF;border-radius:4px;'
                  f'font-size:11px;line-height:16px;margin-bottom:3px;'
                  f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'
                  f'text-align:left">{dot}<b>{html.escape(p.brand)}</b> '
                  f'{ptype}</div>')
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
