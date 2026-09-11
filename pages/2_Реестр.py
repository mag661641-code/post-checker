"""Страница «Реестр»: таблица замечаний по листу «Реестр постов»."""
from __future__ import annotations

import streamlit as st

from ui_common import (issues_to_df, level_filter_widget, page_setup,
                       require_file)

page_setup("Реестр", "📋")
st.title("Замечания по реестру")
st.caption("Номер строки совпадает с номером строки в Excel.")

if not require_file():
    st.stop()

res = st.session_state.get("results") or {}
issues = res.get("registry", [])

levels = level_filter_widget("reg_levels")
issues = [i for i in issues if i.level in levels]

df = issues_to_df(issues)
if df.empty:
    st.success("По реестру замечаний нет. 🎉")
else:
    st.dataframe(
        df, use_container_width=True, hide_index=True,
        column_config={
            "Ссылка": st.column_config.LinkColumn("Ссылка"),
            "Суть замечания": st.column_config.TextColumn(width="large"),
            "Как исправить": st.column_config.TextColumn(width="large"),
        },
    )
    st.caption(f"Всего строк: {len(df)}")
