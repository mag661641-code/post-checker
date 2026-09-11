"""Страница «Экспорт»: скачивание отчёта в .xlsx и .csv."""
from __future__ import annotations

import datetime as dt

import streamlit as st

from ui_common import cached_load, page_setup, require_file, summarize
from checker import report_mod
from checker.models import Level

page_setup("Экспорт", "💾")
st.title("Экспорт отчёта")

file_bytes = require_file()
if not file_bytes:
    st.stop()

wb = cached_load(file_bytes)
res = st.session_state.get("results") or {}
registry = res.get("registry", [])
text = list(res.get("text", [])) + st.session_state.get("spelling_issues", [])
holiday = res.get("holiday", [])
online = st.session_state.get("online_issues", [])

all_issues = registry + text + holiday + online
total_posts = sum(len(v) for v in wb.posts.values())
summary = summarize(all_issues, total_posts)

st.subheader("Что попадёт в отчёт")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Реестр", len(registry))
c2.metric("Тексты", len(text))
c3.metric("Праздники", len(holiday))
c4.metric("Онлайн", len(online))

st.write("Отчёт содержит листы: **Сводка**, **Реестр**, **Тексты**, "
         "**Праздники**, **Онлайн**. Строки раскрашены по уровню, шапка "
         "закреплена, включён автофильтр.")

stamp = dt.date.today().strftime("%Y-%m-%d")
try:
    xlsx = report_mod.build_xlsx(registry + text, summary,
                                 holiday_issues=holiday, online_issues=online)
    st.download_button("⬇️ Скачать отчёт (.xlsx)", data=xlsx,
                       file_name=f"Отчёт проверки постов {stamp}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument."
                            "spreadsheetml.sheet", type="primary")
except Exception as e:  # noqa: BLE001
    st.error(f"Не удалось собрать xlsx: {e}")

try:
    csv = report_mod.build_csv(all_issues)
    st.download_button("⬇️ Скачать отчёт (.csv)", data=csv,
                       file_name=f"Отчёт проверки постов {stamp}.csv",
                       mime="text/csv")
except Exception as e:  # noqa: BLE001
    st.error(f"Не удалось собрать csv: {e}")
