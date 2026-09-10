"""Страница «Тексты постов»: посты с замечаниями, подсветкой и превью фото."""
from __future__ import annotations

import html
import re
from collections import defaultdict

import streamlit as st

from ui_common import cached_load, get_config, page_setup, require_file
from checker import speller
from checker.models import Level

page_setup("Тексты постов", "✍️")
st.title("✍️ Тексты постов")

file_bytes = require_file()
if not file_bytes:
    st.stop()

wb = cached_load(file_bytes)
res = st.session_state.get("results") or {}
text_issues = list(res.get("text", []))

# --- орфография (нужен интернет, по кнопке) ---
st.sidebar.header("Орфография")
st.sidebar.caption("Проверка через Яндекс.Спеллер (нужен интернет).")
if st.sidebar.button("🔤 Проверить орфографию"):
    cfg = get_config()
    prog = st.sidebar.progress(0.0)
    spell = speller.run_spelling(wb.posts, cfg["whitelist"], cfg["rules"],
                                 progress_cb=lambda f: prog.progress(min(f, 1.0)))
    st.session_state["spelling_issues"] = spell
    prog.empty()
    st.sidebar.success(f"Найдено: {len(spell)}")
text_issues += st.session_state.get("spelling_issues", [])

# сгруппировать замечания по (лист, строка)
by_post: dict[tuple, list] = defaultdict(list)
for i in text_issues:
    by_post[(i.sheet, i.row)].append(i)

_LEVEL_COLOR = {Level.ERROR: "#f8cbad", Level.WARNING: "#ffe699",
                Level.ADVICE: "#bdd7ee", Level.TECH: "#d9d9d9"}

# фильтры
st.sidebar.header("Фильтры")
brand_sel = st.sidebar.multiselect("Бренд", sorted(wb.posts.keys()))
only_with_issues = st.sidebar.checkbox("Только посты с замечаниями", value=True)
min_level = st.sidebar.selectbox(
    "Показывать посты не ниже уровня",
    ["🔵 Совет", "🟡 Предупреждение", "🔴 Ошибка"], index=0)
_min = {"🔵 Совет": 3, "🟡 Предупреждение": 2, "🔴 Ошибка": 1}[min_level]
_rank = {Level.ERROR: 1, Level.WARNING: 2, Level.ADVICE: 3, Level.TECH: 4}


def highlight(text: str, issues) -> str:
    """Подсветить проблемные фрагменты. Простое выделение по вхождению слова."""
    safe = html.escape(text)
    for iss in issues:
        m = re.search(r"«([^»]+)»", iss.message)
        if m:
            frag = html.escape(m.group(1))
            color = _LEVEL_COLOR.get(iss.level, "#eee")
            safe = safe.replace(
                frag, f'<mark style="background:{color}">{frag}</mark>', 1)
    return safe.replace("\n", "<br>")


brands = brand_sel or list(wb.posts.keys())
shown = 0
for code in brands:
    posts = wb.posts.get(code, [])
    for post in posts:
        issues = by_post.get((post.sheet, post.row), [])
        if only_with_issues and not issues:
            continue
        if issues and min([_rank[i.level] for i in issues], default=9) > _min:
            continue
        shown += 1
        errs = sum(1 for i in issues if i.level == Level.ERROR)
        warns = sum(1 for i in issues if i.level == Level.WARNING)
        advs = sum(1 for i in issues if i.level == Level.ADVICE)
        title = (f"{code} · строка {post.row} · {post.post_type or 'без типа'} "
                 f"— 🔴 {errs}  🟡 {warns}  🔵 {advs}")
        with st.expander(title):
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(
                    f'<div style="white-space:pre-wrap;border:1px solid #ddd;'
                    f'padding:8px;border-radius:6px">{highlight(post.text, issues)}'
                    f'</div>', unsafe_allow_html=True)
            with col2:
                for ph in post.photos:
                    direct = re.sub(r"^(ЛОГО:|БЕЗ ЛОГО:|ЯБ:|СОЦ:)\s*", "", ph).strip()
                    if re.match(r"https?://i\.ibb\.co/", direct):
                        st.image(direct, use_container_width=True)
                    else:
                        st.caption("🖼 " + ph[:60])
            if issues:
                st.markdown("**Замечания:**")
                for iss in sorted(issues, key=lambda x: _rank[x.level]):
                    st.markdown(f"- {iss.level.emoji} **{iss.message}** "
                                f"_{iss.fix}_")
            if post.stats_comments:
                st.info("💬 Комментарии к посту: " + " | ".join(post.stats_comments))

if shown == 0:
    st.success("Постов по заданным фильтрам нет или замечаний не найдено. 🎉")
else:
    st.caption(f"Показано постов: {shown}")
