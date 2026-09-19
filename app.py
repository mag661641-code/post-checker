"""Маршрутизатор Streamlit. В меню не показывается.

Запуск:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from ui import common as C
from ui import posts, holidays, publications, settings

C.page_config()
C.inject_theme_css()

if not C.require_auth():
    st.stop()

# --- подтянуть настройки из таблицы настроек (один раз за сессию) ---
C.pull_settings()

# --- боковая панель: источник данных + вход/выход ---
C.sidebar()

# --- навигация: 4 пункта (без эмодзи в меню) ---
nav = st.navigation([
    st.Page(posts.render, title="Проверка постов",
            url_path="posts", default=True),
    st.Page(holidays.render, title="Обязательные праздники",
            url_path="holidays"),
    st.Page(publications.render, title="Проверка публикаций",
            url_path="publications"),
    st.Page(settings.render, title="Настройки",
            url_path="settings"),
])

nav.run()
