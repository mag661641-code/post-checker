"""Экран «Проверка постов» — раскладка «Шапка 2 · сводка плитками».

Порядок: месяц и действия → плитки-фильтры по уровню → вид + бренды →
разделитель → контент вида (Посты / Календарь / Замечания).
Меняется только вёрстка; проверки, фильтрация и загрузка — из пакета checker.
"""
from __future__ import annotations

import calendar as _cal
import datetime as dt
import html
import re

import pandas as pd
import streamlit as st

from checker import config_mod, loader_mod
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

# Цвета уровней (дизайн-система ИМП) + значок-квадрат в markdown-разметке.
_LVL = {
    Level.ERROR: {"dot": "#D42525", "bg": "#EBD7D7", "fg": "#C01616",
                  "name": "Ошибка", "plural": "Ошибки"},
    Level.WARNING: {"dot": "#F0AC17", "bg": "#FFE26C", "fg": "#1E1E1E",
                    "name": "Предупреждение", "plural": "Предупреждения"},
    Level.ADVICE: {"dot": "#1D42A5", "bg": "#DADFEC", "fg": "#1D42A5",
                   "name": "Совет", "plural": "Советы"},
}
_LEVELS = [Level.ERROR, Level.WARNING, Level.ADVICE]
_SEV_LEVEL = {"err": Level.ERROR, "warn": Level.WARNING, "tip": Level.ADVICE}
_MD_SQUARE = {Level.ERROR: ":red[■]", Level.WARNING: ":orange[■]",
              Level.ADVICE: ":blue[■]"}


# ---------------------------------------------------------------------------
# Мелкие помощники
# ---------------------------------------------------------------------------
def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text or "").strip()


def _text_preview(post: PostRecord, limit: int = 70) -> str:
    t = _strip_emoji(post.text)
    if not t:
        return "(текст не заполнен)"
    t = re.sub(r"\s+", " ", t)
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0]
    return (cut or t[:limit]) + "…"


def _rule_name(code: str, fallback: str = "") -> str:
    return _CODE_NAME.get(code, fallback or code)


def _post_sev(issues: list[Issue]):
    for lvl in _LEVELS:
        if any(i.level == lvl for i in issues):
            return lvl
    return None


def _md_badges(iss: list[Issue]) -> str:
    parts = []
    for lvl in _LEVELS:
        n = sum(1 for i in iss if i.level == lvl)
        if n:
            parts.append(f"{_MD_SQUARE[lvl]} {n}")
    return " ".join(parts) if parts else "✅"


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


def _set_period(year: int, month: int) -> None:
    st.session_state["period"] = (year, month)
    st.session_state["period_note"] = ""
    st.rerun()


def _set_sev(code: str) -> None:
    st.session_state["sev"] = code
    st.rerun()


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def render() -> None:
    file_bytes = st.session_state.get("file_bytes")
    if not file_bytes:
        C.empty_no_file()
        return

    data = C.build_app_data(file_bytes)
    C.ensure_period(data)
    period = C.current_period()

    # отложенное переключение вида (клик из календаря): применяем до виджета
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

    brand_codes = list(data.cfg["brands"].keys())
    brand_sel = st.session_state.get("flt_brand") or "Все"
    brands = brand_codes if brand_sel == "Все" else [brand_sel]

    # посты месяца по бренду (без учёта уровня/статуса/поиска) — для плиток
    base = C.apply_filters(data, {"brands": brands, "status": [], "search": "",
                                  "levels": [], "only_issues": False}, period)

    _header(data, period, base)
    _tiles(base)
    view = _view_and_brands(data, brand_codes)
    st.divider()

    if view == "Посты":
        _view_posts(data, base, period)
    elif view == "Календарь":
        _view_calendar(data, base, period)
    else:
        _view_issues(data, base, period)


# ---------------------------------------------------------------------------
# Строка 1 — месяц и действия
# ---------------------------------------------------------------------------
def _header(data: C.AppData, period, base) -> None:
    today = C.moscow_today()
    year, month = period if isinstance(period, tuple) else (today.year, today.month)

    note = st.session_state.get("period_note")
    if note:
        st.info(note)

    py, pm = C._shift_month(year, month, -1)
    ny, nm = C._shift_month(year, month, +1)

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


# ---------------------------------------------------------------------------
# Строка 2 — плитки-фильтры по уровню
# ---------------------------------------------------------------------------
def _tiles(base) -> None:
    total = len(base)
    with_issues = sum(1 for _, iss in base if iss)
    cnt = {lvl: sum(1 for _, iss in base for i in iss if i.level == lvl)
           for lvl in _LEVELS}
    sev = st.session_state.get("sev", "all")

    def _t(col, code, label, help_):
        if col.button(label, key=f"tile_{code}", use_container_width=True,
                      help=help_, type="primary" if sev == code else "secondary"):
            _set_sev(code)

    k = st.columns(4)
    _t(k[0], "all", f"Все посты · **{total}** · {with_issues} с замечаниями", None)
    _t(k[1], "err", f":red[■] Ошибки · **{cnt[Level.ERROR]}**",
       "Исправить до публикации")
    _t(k[2], "warn", f":orange[■] Предупреждения · **{cnt[Level.WARNING]}**",
       "Желательно поправить")
    _t(k[3], "tip", f":blue[■] Советы · **{cnt[Level.ADVICE]}**",
       "Можно улучшить")


# ---------------------------------------------------------------------------
# Строка 3 — вид и бренды
# ---------------------------------------------------------------------------
def _view_and_brands(data: C.AppData, brand_codes: list[str]) -> str:
    cols = st.columns([5, 7], vertical_alignment="center")
    with cols[0]:
        view = st.segmented_control(
            "Вид", ["Посты", "Календарь", "Замечания"], key="posts_view",
            label_visibility="collapsed")
    with cols[1]:
        st.pills("Бренд", ["Все"] + brand_codes, selection_mode="single",
                 key="flt_brand", label_visibility="collapsed")
    return view or "Посты"


# ---------------------------------------------------------------------------
# Вид «Посты»
# ---------------------------------------------------------------------------
def _view_posts(data: C.AppData, base, period) -> None:
    rules = data.cfg["rules"]
    sev = st.session_state.get("sev", "all")

    # тулбар: поиск, статус, «только с замечаниями»
    f = st.columns([5, 4, 3], vertical_alignment="center")
    f[0].text_input("Поиск", key="flt_search", label_visibility="collapsed",
                    placeholder="Поиск по тексту поста")
    f[1].pills("Статус", ["Все", "Готово", "Выложено"], selection_mode="single",
               key="flt_status", label_visibility="collapsed")
    f[2].toggle("Только с замечаниями", key="flt_only")

    # отфильтровать по уровню (плитка), статусу, поиску, «только с замечаниями»
    status_sel = st.session_state.get("flt_status") or "Все"
    search = (st.session_state.get("flt_search") or "").strip().lower()
    only = st.session_state.get("flt_only", True)
    disp = []
    for p, iss in base:
        if sev in _SEV_LEVEL and not any(i.level == _SEV_LEVEL[sev] for i in iss):
            continue
        if status_sel != "Все" and \
                data.post_status.get((p.sheet, p.row), "") != status_sel:
            continue
        if search and search not in (p.text or "").lower():
            continue
        if only and not iss:
            continue
        disp.append((p, iss))

    if st.session_state.get("flt_sort") == "Сначала с ошибками":
        disp.sort(key=lambda x: (0 if _post_sev(x[1]) == Level.ERROR else 1,
                                 x[0].date or dt.date.max))
    else:
        disp.sort(key=lambda x: (x[0].date or dt.date.max, x[0].sheet, x[0].row))

    # строка над списком: счётчик · сортировка · развернуть/свернуть
    t = st.columns([4, 4, 2, 2], vertical_alignment="center")
    t[0].markdown(f"**{C.plural_posts(len(disp))}**")
    t[1].segmented_control("Сортировка", ["По дате", "Сначала с ошибками"],
                           key="flt_sort", label_visibility="collapsed")
    if t[2].button("Развернуть все", key="exp_all", use_container_width=True):
        st.session_state["posts_expanded"] = True
    if t[3].button("Свернуть все", key="col_all", use_container_width=True):
        st.session_state["posts_expanded"] = False

    expand_all = st.session_state.get("posts_expanded", False)
    sel = st.session_state.get("sel_post")
    open_once = st.session_state.pop("open_post_once", False)

    # пост из календаря — первым
    if sel is not None:
        disp.sort(key=lambda x: 0 if (x[0].sheet, x[0].row) == sel else 1)

    if not disp:
        st.info("Постов по выбранным условиям нет.")
    for p, iss in disp:
        key = (p.sheet, p.row)
        is_sel = key == sel
        expanded = expand_all or (is_sel and open_once)
        with st.expander(_expander_label(p, iss, rules), expanded=expanded):
            _post_body(data, p, iss)

    _no_date_block(data)


def _expander_label(post: PostRecord, iss: list[Issue], rules: dict) -> str:
    date = C.fmt_date_compact(post.date) or "без даты"
    ptype = C.norm_type(post.post_type, rules)
    head = " · ".join(x for x in (date, post.brand, ptype) if x)
    return f"{head} · {_md_badges(iss)} · {_text_preview(post, 70)}"


# ---------------------------------------------------------------------------
# Тело раскрытого поста (внутри expander — без своей рамки)
# ---------------------------------------------------------------------------
def _platform_links(post: PostRecord) -> str:
    icons = {"t.me": "Telegram", "vk.com": "VK", "ok.ru": "OK",
             "max.ru": "Max", "dzen.ru": "Дзен"}
    seen: list[str] = []
    for s in post.socials:
        from checker import normalize as N
        name = icons.get(N.link_domain(s.get("link", "")))
        if name and name not in seen:
            seen.append(name)
    return ", ".join(seen)


def _post_body(data: C.AppData, post: PostRecord, issues: list[Issue]) -> None:
    verified = st.session_state["verified"]
    key = (post.sheet, post.row)

    meta = f'Лист «{post.sheet}», строка {post.row}'
    if post.date_note:
        meta += f" · {post.date_note}"
    plats = _platform_links(post)
    if plats:
        meta += f" · Площадки: {plats}"
    st.caption(meta)

    excerpt = html.escape((post.text or "").strip()) or "(текст не заполнен)"
    st.markdown(
        f'<div style="padding:12px 14px;background:#F3F3F3;border-radius:4px;'
        f'font-size:14px;line-height:22px;white-space:pre-wrap">{excerpt}</div>',
        unsafe_allow_html=True)

    # орфография — по кнопке (чтобы не дёргать сервис у всех раскрытых сразу)
    spell_key = f"spell_on_{post.sheet}_{post.row}"
    if (post.text or "").strip() and not st.session_state.get(spell_key):
        if st.button("🔤 Проверить орфографию",
                     key=f"spellbtn_{post.sheet}_{post.row}", type="tertiary"):
            st.session_state[spell_key] = True
            st.rerun()
        spell = []
    else:
        spell = _spell_issues(data, post)

    all_issues = issues + spell
    order = {Level.ERROR: 0, Level.WARNING: 1, Level.ADVICE: 2, Level.TECH: 3}
    all_issues = sorted(all_issues, key=lambda i: order.get(i.level, 9))

    if all_issues:
        st.markdown(f"**Замечания · {len(all_issues)}**")
    for n, iss in enumerate(all_issues):
        _issue_row(post, iss, n)

    _photos(post)

    st.write("")
    b = st.columns([3, 3, 6])
    link = C.sheet_link(post.row, post.sheet)
    if link:
        b[0].link_button("Открыть в таблице", link, use_container_width=True)
    is_done = key in verified
    if b[1].button("Снять отметку" if is_done else "Отметить проверенным",
                   key=f"mark_{post.sheet}_{post.row}", use_container_width=True,
                   type="secondary" if is_done else "primary"):
        verified.discard(key) if is_done else verified.add(key)
        st.rerun()


def _issue_row(post: PostRecord, iss: Issue, n: int) -> None:
    cols = st.columns([9, 1], vertical_alignment="center")
    with cols[0]:
        name = _rule_name(iss.code, iss.message)
        st.markdown(f'{_tag(iss.level)}&nbsp; <b>{html.escape(name)}.</b> '
                    f'<span style="color:#464646">{html.escape(iss.message)}'
                    f'</span>', unsafe_allow_html=True)
        fix = (iss.fix or "").strip()
        if fix and fix not in (iss.message or ""):
            st.caption(f"Как исправить: {fix}")
        frag = _fragment_for_issue(iss)
        frag_html = _frag_html(post.text or "", frag) if frag else None
        if frag_html:
            st.markdown(f'<span style="font-size:14px">Фрагмент: {frag_html}'
                        f'</span>', unsafe_allow_html=True)
    with cols[1]:
        if iss.code == "spell_error":
            if st.button("В словарь", key=f"wl_{post.sheet}_{post.row}_{n}",
                         type="tertiary", help="Добавить слово в словарь"):
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
    st.divider()


def _fragment_for_issue(iss: Issue):
    for pat in (r"«([^»]+)»", r"\[[^\]]+\]", r"#[\wА-Яа-яЁё]+"):
        m = re.search(pat, iss.message)
        if m:
            return m.group(1) if pat.startswith("«") else m.group(0)
    return None


def _frag_html(text: str, frag: str, words: int = 3):
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
# Посты без даты (+ диагностика по листам)
# ---------------------------------------------------------------------------
def _no_date_block(data: C.AppData) -> None:
    rules = data.cfg["rules"]
    brand_sel = st.session_state.get("flt_brand") or "Все"
    no_date = [p for p in data.posts if not p.date
               and (brand_sel == "Все" or p.brand == brand_sel)]

    if no_date:
        st.divider()
        # ВНИМАНИЕ: Streamlit запрещает вложенные expander, поэтому «Посты без
        # даты» — заголовок-секция, а сами посты — раскрывающиеся (как в списке).
        st.markdown(f"##### :material/warning: Посты без даты ({len(no_date)})")
        st.caption("Проставьте дату в таблице, иначе пост не попадёт в проверку "
                   "за месяц.")
        for p in sorted(no_date, key=lambda x: (x.brand, x.sheet, x.row)):
            iss = [i for i in data.issues_by_post.get((p.sheet, p.row), [])
                   if i.level != Level.TECH]
            with st.expander(_expander_label(p, iss, rules)):
                _post_body(data, p, iss)

    _load_diagnostics(data)


def _load_diagnostics(data: C.AppData) -> None:
    """Небольшая диагностика: постов с текстом и из них без даты по листам —
    чтобы сверить контрольные числа загрузчика."""
    by_sheet: dict[str, list[PostRecord]] = {}
    for p in data.posts:
        by_sheet.setdefault(p.sheet, []).append(p)
    st.divider()
    with st.expander("Диагностика загрузки (постов по листам)"):
        rows = []
        for sheet in loader_mod.BRAND_SHEETS:
            ps = by_sheet.get(sheet, [])
            with_text = [p for p in ps if (p.text or "").strip()]
            no_date = [p for p in with_text if not p.date]
            rows.append({"Лист": sheet, "Постов с текстом": len(with_text),
                         "Из них без даты": len(no_date)})
        total_text = sum(r["Постов с текстом"] for r in rows)
        total_nd = sum(r["Из них без даты"] for r in rows)
        rows.append({"Лист": "Итого", "Постов с текстом": total_text,
                     "Из них без даты": total_nd})
        st.dataframe(pd.DataFrame(rows), use_container_width=True,
                     hide_index=True)
        st.caption("Ориентир из таблицы: всего 466, без даты 22 (все на СМУ).")


# ---------------------------------------------------------------------------
# Вид «Календарь»
# ---------------------------------------------------------------------------
def _view_calendar(data: C.AppData, base, period) -> None:
    today = C.moscow_today()
    year, month = period if isinstance(period, tuple) else (today.year, today.month)
    rules = data.cfg["rules"]

    by_day: dict[int, list] = {}
    for p, iss in base:
        by_day.setdefault(p.date.day, []).append((p, iss))

    head = st.columns(7)
    for i, wd in enumerate(["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]):
        head[i].caption(wd)

    for week in _cal.monthcalendar(year, month):
        cols = st.columns(7)
        for i, dnum in enumerate(week):
            with cols[i]:
                with st.container(border=True):
                    if dnum == 0:
                        st.caption(" ")
                        continue
                    is_today = (today.year, today.month, today.day) == \
                        (year, month, dnum)
                    if is_today:
                        st.markdown(f"**{dnum}** · сегодня")
                    else:
                        st.markdown(f"**{dnum}**")
                    items = by_day.get(dnum, [])
                    for p, iss in items[:3]:
                        s = _post_sev(iss)
                        badge = f" {_MD_SQUARE[s]} {len(iss)}" if s else ""
                        ptype = C.norm_type(p.post_type, rules)
                        lbl = f"{p.brand} · {ptype[:12]}{badge}"
                        if st.button(lbl, key=f"cal_{p.sheet}_{p.row}",
                                     type="tertiary", use_container_width=True):
                            st.session_state["sel_post"] = (p.sheet, p.row)
                            st.session_state["open_post_once"] = True
                            st.session_state["force_view"] = "Посты"
                            st.rerun()
                    if len(items) > 3:
                        st.caption(f"ещё {len(items) - 3}")


# ---------------------------------------------------------------------------
# Вид «Замечания» (по типам)
# ---------------------------------------------------------------------------
def _view_issues(data: C.AppData, base, period) -> None:
    by_key = dict(((p.sheet, p.row), (p, iss)) for p, iss in base)
    groups: dict[Level, dict[str, list[tuple]]] = {l: {} for l in _LEVELS}
    for p, iss in base:
        for i in iss:
            if i.level in groups:
                groups[i.level].setdefault(i.code, []).append((p, i))

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
            for code, items in sorted(rules_map.items(), key=lambda kv: -len(kv[1])):
                rid = f"{lvl.value}|{code}"
                n_posts = len({(p.sheet, p.row) for p, _ in items})
                if st.button(f"{_rule_name(code, items[0][1].message)} · {n_posts}",
                             key=f"rule_{rid}", use_container_width=True,
                             type="primary" if rid == sel_rule else "secondary"):
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
                    'Отметьте пост, когда исправите его в таблице.',
                    unsafe_allow_html=True)
        st.progress(done / total if total else 0.0,
                    text=f"Исправлено {done} из {total}")
        st.write("")
        for p, i in posts:
            key = (p.sheet, p.row)
            row = st.columns([1, 3, 2, 8, 3], vertical_alignment="center")
            checked = row[0].checkbox("исправлено", value=key in verified,
                                      key=f"chk_{level_val}_{code}_{p.sheet}_{p.row}",
                                      label_visibility="collapsed")
            verified.add(key) if checked else verified.discard(key)
            muted = "color:#858585;" if key in verified else ""
            row[1].markdown(f'<span style="{muted}">'
                            f'{C.fmt_date_compact(p.date) or "—"}</span>',
                            unsafe_allow_html=True)
            row[2].markdown(f'<span style="font-weight:600;{muted}">{p.brand}'
                            f'</span>', unsafe_allow_html=True)
            row[3].markdown(
                f'<span style="{muted}white-space:nowrap;overflow:hidden;'
                f'text-overflow:ellipsis;display:block">'
                f'{html.escape(_text_preview(p, 80))}</span>',
                unsafe_allow_html=True)
            if row[4].button("Открыть", key=f"open_{level_val}_{code}_{p.sheet}_{p.row}",
                             type="tertiary"):
                st.session_state["sel_post"] = key
                st.session_state["open_post_once"] = True
                st.session_state["force_view"] = "Посты"
                st.rerun()
