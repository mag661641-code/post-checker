"""Экран «Проверка постов»: шапка, выбор месяца, фильтры, вкладки
«Посты» (список + карточка) и «Все замечания».
"""
from __future__ import annotations

import datetime as dt
import html
import re

import pandas as pd
import streamlit as st

from checker import config_mod, loader_mod
from checker.models import Issue, Level, PostRecord
from checker import normalize as N
from ui import common as C

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF"
    "\U00002190-\U000021FF\U00002B00-\U00002BFF️]")

_LEVEL_BG = {Level.ERROR: "#f8cbad", Level.WARNING: "#ffe699",
             Level.ADVICE: None}  # совет — подчёркивание

# Подсказка показывается только на узком экране, где Streamlit ставит
# колонки друг под другом (карточка уезжает под список).
_NARROW_HINT = (
    '<style>.pc-narrow-hint{display:none;color:#888;font-size:.85rem;'
    'margin-bottom:.3rem}@media (max-width:900px){.pc-narrow-hint'
    '{display:block}}</style>'
    '<div class="pc-narrow-hint">Выберите пост — карточка откроется ниже</div>')


def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text or "").strip()


def _text_preview(post: PostRecord, limit: int = 50) -> str:
    t = _strip_emoji(post.text)
    if not t:
        return "(текст не заполнен)"
    t = re.sub(r"\s+", " ", t)
    return t[:limit] + ("…" if len(t) > limit else "")


def render() -> None:
    file_bytes = st.session_state.get("file_bytes")
    if not file_bytes:
        C.empty_no_file()
        return

    data = C.build_app_data(file_bytes)
    C.ensure_period(data)
    period = C.current_period()

    # ---- шапка ----
    st.title(f"Проверка за {C.period_title(period)}")

    C.period_selector(data, key_prefix="posts")
    _period_line(data, period)

    filters = C.filters_bar(data)
    filtered = C.apply_filters(data, filters, period)

    # метрики
    all_issues = [i for _, iss in filtered for i in iss]
    m = st.columns(4)
    m[0].metric("Постов в выборке", len(filtered))
    m[1].metric("🔴 Ошибки", sum(1 for i in all_issues if i.level == Level.ERROR))
    m[2].metric("🟡 Предупреждения",
                sum(1 for i in all_issues if i.level == Level.WARNING))
    m[3].metric("🔵 Советы", sum(1 for i in all_issues if i.level == Level.ADVICE))

    _upcoming_hint(filtered, period)

    tab_posts, tab_all = st.tabs(["Посты", "Все замечания"])
    with tab_posts:
        _tab_posts(data, filtered, filters)
    with tab_all:
        _tab_all_issues(data, filtered)


# ---------------------------------------------------------------------------
# Посты без даты
# ---------------------------------------------------------------------------
def _period_line(data: C.AppData, period) -> None:
    """Одна строка под выбором периода: сколько постов за месяц и без даты."""
    total = len(C.posts_in_period(data, period))
    no_date = [p for p in data.posts if not p.date]
    if total == 0:
        base = f"За {C.period_title(period)} постов в таблице пока нет"
    else:
        base = f"За {C.period_title(period)}: {C.plural_posts(total)}"
    if no_date:
        row = st.columns([6, 3], vertical_alignment="center")
        row[0].caption(f"{base} · ещё {len(no_date)} без даты")
        if row[1].button("показать", key="show_no_date", type="tertiary"):
            _no_date_dialog(no_date)
    else:
        st.caption(base)


@st.dialog("Посты без даты публикации")
def _no_date_dialog(posts: list[PostRecord]) -> None:
    st.caption("У этих постов не заполнена дата — проставьте её в таблице, "
               "чтобы они попали в нужный месяц.")
    rows = [{"Лист": p.sheet, "Строка Excel": p.row,
             "Начало текста": _text_preview(p)} for p in posts]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True,
                 height=min(400, 60 + 35 * len(rows)))


# ---------------------------------------------------------------------------
# Подсказка про ближайшие дни
# ---------------------------------------------------------------------------
def _upcoming_hint(filtered, period) -> None:
    today = C.moscow_today()
    if period != (today.year, today.month):
        return
    horizon = today + dt.timedelta(days=2)
    cnt = 0
    for p, iss in filtered:
        if p.date and today <= p.date <= horizon and \
           any(i.level == Level.ERROR for i in iss):
            cnt += 1
    if cnt:
        st.warning(f"{cnt} постов с ошибками запланированы на ближайшие 2 дня.")


# ---------------------------------------------------------------------------
# Вкладка «Посты»
# ---------------------------------------------------------------------------
def _tab_posts(data: C.AppData, filtered, filters) -> None:
    if not filtered:
        st.success("Постов с замечаниями нет 🎉")
        st.button("Сбросить фильтры", on_click=C._reset_filters,
                  key="reset_empty")
        return

    rules = data.cfg["rules"]

    def err_count(iss):
        return sum(1 for i in iss if i.level == Level.ERROR)

    left, right = st.columns([5, 6], gap="medium")

    with left:
        st.markdown(_NARROW_HINT, unsafe_allow_html=True)

        # строка над таблицей: сортировка · счётчик · орфография
        top = st.columns([5, 2, 4], vertical_alignment="center")
        with top[0]:
            sort_mode = st.segmented_control(
                "Сортировка", ["По дате", "Сначала с ошибками"],
                default="По дате", key="sort_mode",
                label_visibility="collapsed")
        with top[1]:
            st.caption(f"{len(filtered)} постов")
        with top[2]:
            spell_clicked = st.button("🔤 Проверить орфографию во всех",
                                      key="spell_all_btn", type="tertiary",
                                      use_container_width=True)

        sort_mode = sort_mode or "По дате"
        if sort_mode == "Сначала с ошибками":
            filtered = sorted(filtered, key=lambda x: (-err_count(x[1]),
                              x[0].date or dt.date.max))
        else:
            filtered = sorted(filtered, key=lambda x: (x[0].date or dt.date.max,
                              x[0].sheet, x[0].row))

        df_rows = []
        for p, iss in filtered:
            df_rows.append({
                "Дата": C.fmt_date_compact(p.date) or "без даты",
                "Бренд": p.brand,
                "Замечания": _issue_badges(iss),
                "Пост": _post_cell(p, rules),
            })
        df = pd.DataFrame(df_rows)
        event = st.dataframe(
            df, use_container_width=True, hide_index=True,
            on_select="rerun", selection_mode="single-row", height=560,
            column_config={
                "Дата": st.column_config.TextColumn(width="small"),
                "Бренд": st.column_config.TextColumn(width="small"),
                "Замечания": st.column_config.TextColumn(width="small"),
                "Пост": st.column_config.TextColumn(width="large"),
            })
        sel = event.selection.rows if event and event.selection else []
        idx = sel[0] if sel else 0

        if spell_clicked:
            _spell_all_fragment(data, filtered)

    with right:
        post, p_issues = filtered[idx]
        _post_card(data, post, p_issues)


def _issue_badges(iss: list[Issue]) -> str:
    """Счётчики замечаний одной строкой: «🔴 2  🟡 1», нули не показываем."""
    counts = [
        ("🔴", sum(1 for i in iss if i.level == Level.ERROR)),
        ("🟡", sum(1 for i in iss if i.level == Level.WARNING)),
        ("🔵", sum(1 for i in iss if i.level == Level.ADVICE)),
    ]
    parts = [f"{emoji} {n}" for emoji, n in counts if n]
    return "  ".join(parts) if parts else "✅"


def _post_cell(post: PostRecord, rules: dict) -> str:
    """Тип и начало текста в одной ячейке, всего до 70 символов."""
    ptype = C.norm_type(post.post_type, rules)
    prefix = f"{ptype} · " if ptype else ""
    room = max(20, 70 - len(prefix))
    return prefix + _text_preview(post, room)


@st.fragment
def _spell_all_fragment(data: C.AppData, filtered) -> None:
    posts = [p for p, _ in filtered if (p.text or "").strip()]
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
# Карточка поста
# ---------------------------------------------------------------------------
def _post_card(data: C.AppData, post: PostRecord, issues: list[Issue]) -> None:
    rules = data.cfg["rules"]
    ptype = C.norm_type(post.post_type, rules)

    # 1. шапка — заголовок и строка с мета + кнопками
    if post.date:
        st.subheader(f"📅 {C.fmt_date_full(post.date)} · {post.brand} · {ptype}")
    else:
        st.subheader(f"📅 :red[Дата не указана] · {post.brand} · {ptype}")

    status = data.post_status.get((post.sheet, post.row), "")
    meta = f'Лист «{post.sheet}», строка {post.row}'
    if post.executor and post.executor != "-":
        meta += f" · Исполнитель: {post.executor}"
    if post.date_note:
        meta += f" · {post.date_note}"
    plats = _platform_names(post)
    if plats:
        meta += " · Площадки: " + ", ".join(plats)
    if status:
        meta += f" · Статус: {status}"

    hc = st.columns([6, 2, 2], vertical_alignment="center")
    hc[0].caption(meta)
    link = C.sheet_link(post.row, post.sheet)
    if link:
        hc[1].link_button("Открыть в таблице", link, use_container_width=True)
    if post.text:
        with hc[2].popover("📋 Копировать текст", use_container_width=True):
            st.code(post.text, language=None)

    # 2. текст с подсветкой
    st.markdown(_highlight(post.text, issues), unsafe_allow_html=True)

    # орфография (автоматически, кешируется)
    spell_issues = _spell_issues(data, post)

    # 3. замечания
    all_issues = issues + spell_issues
    _issue_list(data, post, all_issues)

    # 4. фото
    _photos(post)


def _platform_names(post: PostRecord) -> list[str]:
    icons = {"t.me": "Telegram", "vk.com": "VK", "ok.ru": "OK",
             "max.ru": "Max", "dzen.ru": "Дзен"}
    seen: list[str] = []
    for s in post.socials:
        name = icons.get(N.link_domain(s.get("link", "")))
        if name and name not in seen:
            seen.append(name)
    return seen


def _fragment_for_issue(iss: Issue) -> str | None:
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


def _highlight(text: str, issues: list[Issue]) -> str:
    safe = html.escape(text or "")
    # подсвечиваем по одному вхождению каждого найденного фрагмента
    for iss in issues:
        frag = _fragment_for_issue(iss)
        if not frag:
            continue
        frag_safe = html.escape(frag)
        if frag_safe not in safe:
            continue
        tip = html.escape(iss.message)
        if iss.level == Level.ERROR:
            repl = f'<mark title="{tip}" style="background:#f8cbad">{frag_safe}</mark>'
        elif iss.level == Level.WARNING:
            repl = f'<mark title="{tip}" style="background:#ffe699">{frag_safe}</mark>'
        else:
            repl = (f'<span title="{tip}" style="text-decoration:underline '
                    f'wavy #2b78c4">{frag_safe}</span>')
        safe = safe.replace(frag_safe, repl, 1)
    return (f'<div style="white-space:pre-wrap;border:1px solid #ddd;'
            f'padding:10px;border-radius:6px;max-height:340px;overflow:auto">'
            f'{safe}</div>')


def _spell_issues(data: C.AppData, post: PostRecord) -> list[Issue]:
    if not (post.text or "").strip():
        return []
    placeholder = st.empty()
    placeholder.caption("проверяем орфографию…")
    status, words = C.spell_for_post(post, data.cfg)
    placeholder.empty()
    if status == "unavailable":
        st.caption("Орфографию проверить не удалось, нет связи с сервисом.")
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


def _issue_list(data: C.AppData, post: PostRecord, issues: list[Issue]) -> None:
    if not issues:
        st.success("Замечаний нет 🎉")
        return
    order = {Level.ERROR: 0, Level.WARNING: 1, Level.ADVICE: 2, Level.TECH: 3}
    ordered = sorted(issues, key=lambda i: order.get(i.level, 9))

    show_key = f"show_all_{post.sheet}_{post.row}"
    limit = 5
    show_all = st.session_state.get(show_key, False)
    visible = ordered if show_all else ordered[:limit]

    for n, iss in enumerate(visible):
        with st.container(border=True):
            cols = st.columns([8, 2], vertical_alignment="center")
            with cols[0]:
                st.markdown(f"{iss.level.emoji} {iss.message}")
                if iss.fix:
                    st.caption(iss.fix)
            with cols[1]:
                if iss.code == "spell_error":
                    if st.button("Добавить слово",
                                 key=f"wl_{post.row}_{n}_{iss.code}",
                                 type="tertiary", use_container_width=True,
                                 help="Добавить в словарь орфографии"):
                        config_mod.add_word_to_whitelist(iss.extra.get("word", ""))
                        C.persist_all()
                        st.rerun()
                else:
                    if st.button("Не ошибка",
                                 key=f"ig_{post.row}_{n}_{iss.code}",
                                 type="tertiary", use_container_width=True,
                                 help="Скрыть это замечание"):
                        chash = config_mod.content_hash(post.text)
                        config_mod.add_ignored(iss.sheet, iss.code, chash,
                                               row=post.row)
                        C.persist_all()
                        st.rerun()

    hidden = len(ordered) - len(visible)
    if hidden > 0:
        if st.button(f"Показать ещё {hidden}",
                     key=f"more_{post.sheet}_{post.row}"):
            st.session_state[show_key] = True
            st.rerun()


_PHOTO_TAG_RE = re.compile(r"^(ЛОГО|БЕЗ ЛОГО|ЯБ|СОЦ)\s*:\s*", re.IGNORECASE)


def _photo_parts(ph: str, i: int) -> tuple[str, str, str]:
    """(подпись превью, подпись кнопки, прямая ссылка)."""
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
                    st.caption("🖼 " + (direct or caption)[:40])


# ---------------------------------------------------------------------------
# Вкладка «Все замечания»
# ---------------------------------------------------------------------------
def _tab_all_issues(data: C.AppData, filtered) -> None:
    # замечания по отфильтрованным постам + реестр за месяц
    rows = []
    period = C.current_period()
    seen_post_keys = {(p.sheet, p.row) for p, _ in filtered}

    collected: list[Issue] = []
    for _, iss in filtered:
        collected.extend(iss)
    for i in data.issues:
        if i.sheet == loader_mod.REGISTRY_SHEET and \
           C.period_matches(C.issue_date(i, data), period):
            collected.append(i)

    for i in collected:
        d = C.issue_date(i, data)
        rows.append({
            "Уровень": f"{i.level.emoji} {i.level.title_ru}",
            "Дата поста": C.fmt_date_short(d) if d else "",
            "Бренд": i.brand,
            "Где": f"{i.sheet}, строка {i.row}",
            "Открыть": C.sheet_link(i.row, i.sheet) or "",
            "Суть": i.message,
            "Как исправить": i.fix,
        })
    if not rows:
        st.info("Замечаний по выбранным фильтрам нет.")
        return
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True, height=560,
                 column_config={
                     "Открыть": st.column_config.LinkColumn(
                         "Открыть", display_text="в таблице"),
                     "Суть": st.column_config.TextColumn(width="large"),
                     "Как исправить": st.column_config.TextColumn(width="large"),
                 })
    st.caption(f"Всего замечаний: {len(rows)}")
