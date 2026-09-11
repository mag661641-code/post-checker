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


def _strip_emoji(text: str) -> str:
    return _EMOJI_RE.sub("", text or "").strip()


def _text_preview(post: PostRecord) -> str:
    t = _strip_emoji(post.text)
    if not t:
        return "(текст не заполнен)"
    t = re.sub(r"\s+", " ", t)
    return t[:50] + ("…" if len(t) > 50 else "")


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

    C.month_selector(data, key_prefix="posts")
    _posts_without_date(data, period)

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
def _posts_without_date(data: C.AppData, period) -> None:
    if period is None:
        return
    no_date = [p for p in data.posts if not p.date]
    if not no_date:
        return
    if st.button(f"Ещё {len(no_date)} постов без даты — показать",
                 key="show_no_date"):
        _no_date_dialog(no_date)


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

    sort_mode = st.segmented_control("Сортировка", ["По дате", "Сначала с ошибками"],
                                     default="По дате", key="sort_mode")

    def err_count(iss):
        return sum(1 for i in iss if i.level == Level.ERROR)

    if sort_mode == "Сначала с ошибками":
        filtered = sorted(filtered, key=lambda x: (-err_count(x[1]),
                          x[0].date or dt.date.max))
    else:
        filtered = sorted(filtered, key=lambda x: (x[0].date or dt.date.max,
                          x[0].sheet, x[0].row))

    left, right = st.columns([2, 3])

    with left:
        _spell_all_button(data, filtered)
        df_rows = []
        for p, iss in filtered:
            df_rows.append({
                "Дата публикации": C.fmt_date_short(p.date) or "без даты",
                "Бренд": p.brand,
                "Тип": C.norm_type(p.post_type, data.cfg["rules"]),
                "Начало текста": _text_preview(p),
                "🔴": err_count(iss),
                "🟡": sum(1 for i in iss if i.level == Level.WARNING),
                "🔵": sum(1 for i in iss if i.level == Level.ADVICE),
            })
        df = pd.DataFrame(df_rows)
        event = st.dataframe(
            df, use_container_width=True, hide_index=True,
            on_select="rerun", selection_mode="single-row", height=560,
            column_config={
                "Дата публикации": st.column_config.TextColumn(width="medium"),
                "Начало текста": st.column_config.TextColumn(width="large"),
                "🔴": st.column_config.NumberColumn(width="small"),
                "🟡": st.column_config.NumberColumn(width="small"),
                "🔵": st.column_config.NumberColumn(width="small"),
            })
        sel = event.selection.rows if event and event.selection else []
        idx = sel[0] if sel else 0

    with right:
        post, p_issues = filtered[idx]
        _post_card(data, post, p_issues)


def _spell_all_button(data: C.AppData, filtered) -> None:
    if st.button("Проверить орфографию во всех постах выборки",
                 key="spell_all_btn"):
        _spell_all_fragment(data, filtered)


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

    # 1. заголовок
    if post.date:
        st.subheader(f"📅 {C.fmt_date_full(post.date)} · {post.brand} · {ptype}")
    else:
        st.subheader(f"📅 :red[Дата не указана] · {post.brand} · {ptype}")
    status = data.post_status.get((post.sheet, post.row), "")
    meta = f'Лист «{post.sheet}», строка Excel {post.row}'
    if post.executor and post.executor != "-":
        meta += f" · Исполнитель: {post.executor}"
    if status:
        meta += f" · Статус: {status}"
    st.caption(meta)

    # 2. площадки
    _platforms(post)

    # 3. текст с подсветкой
    st.markdown(_highlight(post.text, issues), unsafe_allow_html=True)

    # орфография (автоматически, кешируется)
    spell_issues = _spell_issues(data, post)

    # 4. замечания
    all_issues = issues + spell_issues
    _issue_list(data, post, all_issues)

    # 5. фото
    _photos(post)

    # 6. копирование текста
    if post.text:
        with st.expander("📋 Скопировать текст поста"):
            st.code(post.text, language=None)


def _platforms(post: PostRecord) -> None:
    icons = {"t.me": "Telegram", "vk.com": "VK", "ok.ru": "OK",
             "max.ru": "Max", "dzen.ru": "Дзен"}
    seen = {}
    for s in post.socials:
        link = s.get("link", "")
        d = N.link_domain(link)
        name = icons.get(d)
        if name and name not in seen:
            seen[name] = link
    if not seen:
        return
    parts = []
    for name, link in seen.items():
        if link:
            parts.append(f"[{name}]({link})")
        else:
            parts.append(name)
    st.markdown("**Площадки:** " + " · ".join(parts))


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
    for lvl in [Level.ERROR, Level.WARNING, Level.ADVICE]:
        group = [i for i in issues if i.level == lvl]
        if not group:
            continue
        st.markdown(f"**{C.LEVEL_LABELS[lvl]}**")
        for n, iss in enumerate(group):
            cols = st.columns([6, 1.4])
            with cols[0]:
                st.markdown(f"{iss.level.emoji} {iss.message}")
                if iss.fix:
                    st.caption(iss.fix)
            with cols[1]:
                if iss.code == "spell_error":
                    if st.button("Добавить слово", key=f"wl_{post.row}_{n}_{iss.code}",
                                 help="Добавить в словарь орфографии"):
                        config_mod.add_word_to_whitelist(iss.extra.get("word", ""))
                        C.cached_spell.clear()
                        st.rerun()
                else:
                    if st.button("Не ошибка",
                                 key=f"ig_{post.row}_{n}_{iss.code}",
                                 help="Скрыть это замечание"):
                        config_mod.add_ignored(iss.sheet, iss.row, iss.code)
                        C.cached_base_checks.clear()
                        st.rerun()


def _photos(post: PostRecord) -> None:
    if not post.photos:
        return
    for ph in post.photos:
        direct = re.sub(r"^(ЛОГО:|БЕЗ ЛОГО:|ЯБ:|СОЦ:)\s*", "", ph).strip()
        if re.match(r"https?://i\.ibb\.co/", direct):
            st.image(direct, width=280)
        elif direct.lower().startswith("http"):
            st.link_button("Открыть фото", direct)
        else:
            st.caption("🖼 " + ph[:60])


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
            "Суть": i.message,
            "Как исправить": i.fix,
        })
    if not rows:
        st.info("Замечаний по выбранным фильтрам нет.")
        return
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True, height=560,
                 column_config={
                     "Суть": st.column_config.TextColumn(width="large"),
                     "Как исправить": st.column_config.TextColumn(width="large"),
                 })
    st.caption(f"Всего замечаний: {len(rows)}")
