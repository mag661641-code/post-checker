"""Страница «Сводка»: метрики, графики, фильтры."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ui_common import (all_issues_from_state, cached_load, issues_to_df,
                       level_filter_widget, page_setup, require_file)
from checker.models import Level

page_setup("Сводка", "📊")
st.title("Сводка")

file_bytes = require_file()
if not file_bytes:
    st.stop()

wb = cached_load(file_bytes)
issues = all_issues_from_state()
total_posts = sum(len(v) for v in wb.posts.values())

# --- метрики ---
c1, c2, c3, c4 = st.columns(4)
c1.metric("Всего постов", total_posts)
c2.metric("🔴 Ошибок", sum(1 for i in issues if i.level == Level.ERROR))
c3.metric("🟡 Предупреждений", sum(1 for i in issues if i.level == Level.WARNING))
c4.metric("🔵 Советов", sum(1 for i in issues if i.level == Level.ADVICE))

df = issues_to_df(issues)

# --- боковые фильтры ---
st.sidebar.header("Фильтры")
brands = sorted({i.brand for i in issues if i.brand})
execs = sorted({i.executor for i in issues if i.executor})
types = sorted({i.post_type for i in issues if i.post_type})
statuses = sorted({i.status for i in issues if i.status})

sel_brand = st.sidebar.multiselect("Бренд", brands)
sel_type = st.sidebar.multiselect("Тип поста", types)
sel_status = st.sidebar.multiselect("Статус", statuses)
levels = level_filter_widget("summary_levels")

fdf = df.copy()
if not fdf.empty:
    fdf = fdf[fdf["Уровень"].isin({f"{l.emoji} {l.title_ru}" for l in levels})]
    if sel_brand:
        fdf = fdf[fdf["Бренд"].isin(sel_brand)]
    if sel_type:
        fdf = fdf[fdf["Тип поста"].isin(sel_type)]
    if sel_status:
        fdf = fdf[fdf["Статус"].isin(sel_status)]

st.divider()

# --- графики ---
col_a, col_b = st.columns(2)
with col_a:
    st.subheader("Замечания по брендам")
    if not fdf.empty and fdf["Бренд"].str.len().gt(0).any():
        by_brand = fdf[fdf["Бренд"] != ""].groupby("Бренд").size()
        st.bar_chart(by_brand)
    else:
        st.caption("Нет данных для графика.")

with col_b:
    st.subheader("Замечания по уровням")
    if not fdf.empty:
        by_lvl = fdf.groupby("Уровень").size()
        st.bar_chart(by_lvl)
    else:
        st.caption("Нет данных для графика.")

# --- технические проблемы ---
tech = [i for i in issues if i.level == Level.TECH]
if tech:
    with st.expander(f"⚙️ Технические проблемы проверок ({len(tech)})"):
        for i in tech:
            st.write(f"• [{i.sheet}] {i.message}")

st.divider()
st.subheader(f"Все замечания ({len(fdf)})")
st.dataframe(fdf, use_container_width=True, hide_index=True,
             column_config={"Ссылка": st.column_config.LinkColumn("Ссылка")})
