"""Страница «Онлайн-проверка»: проверка опубликованных постов в интернете."""
from __future__ import annotations

import streamlit as st

from ui_common import cached_load, get_config, issues_to_df, page_setup, require_file
from checker import online_checks

page_setup("Онлайн-проверка", "🌐")
st.title("Онлайн-проверка опубликованных постов")
st.caption("Проверка идёт в интернет и занимает время. Запускается по кнопке. "
           "Работа зависит от самих площадок и может измениться при обновлении "
           "их сайтов.")

file_bytes = require_file()
if not file_bytes:
    st.stop()

wb = cached_load(file_bytes)
cfg = get_config()

vk_key = None
try:
    vk_key = st.secrets.get("vk", {}).get("service_key")  # type: ignore
except Exception:  # noqa: BLE001
    vk_key = None
st.write("Ключ ВКонтакте: " + ("задан ✅" if vk_key else "не задан "
         "(проверяется только доступность страницы)"))

brand_sel = st.multiselect("Бренды для проверки", sorted(wb.posts.keys()),
                           default=sorted(wb.posts.keys()))

if "online_stop" not in st.session_state:
    st.session_state["online_stop"] = False

col1, col2 = st.columns(2)
start = col1.button("▶️ Запустить проверку", type="primary")
if col2.button("⏹ Остановить"):
    st.session_state["online_stop"] = True

if start:
    st.session_state["online_stop"] = False
    subset = {c: wb.posts[c] for c in brand_sel if c in wb.posts}
    progress = st.progress(0.0, text="Проверяем…")

    def cb(frac):
        progress.progress(min(frac, 1.0), text=f"Проверено {frac*100:.0f}%")

    def stop():
        return st.session_state.get("online_stop", False)

    with st.spinner("Идут запросы к площадкам…"):
        issues = online_checks.run_online_checks(
            subset, cfg["rules"], vk_key=vk_key, progress_cb=cb, should_stop=stop)
    st.session_state["online_issues"] = issues
    progress.empty()
    st.success(f"Готово. Найдено замечаний: {len(issues)}.")

issues = st.session_state.get("online_issues", [])
if issues:
    df = issues_to_df(issues)
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={"Ссылка": st.column_config.LinkColumn("Ссылка")})

    # показать построчную разницу для расхождений
    diffs = [i for i in issues if i.extra.get("published") is not None]
    if diffs:
        import difflib
        st.subheader("Расхождения текста (построчно)")
        for i in diffs[:20]:
            with st.expander(f"{i.brand} · строка {i.row} · {i.link}"):
                pub = (i.extra.get("published") or "").split("\n")
                exp = (i.extra.get("expected") or "").split("\n")
                diff = difflib.unified_diff(exp, pub, "согласовано",
                                            "опубликовано", lineterm="")
                st.code("\n".join(diff) or "нет различий", language="diff")
else:
    st.info("Нажмите «Запустить проверку», чтобы проверить публикации.")
