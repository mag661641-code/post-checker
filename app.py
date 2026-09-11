"""Маршрутизатор Streamlit. В меню не показывается.

Запуск:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from ui import common as C
from ui import posts, holidays, publications, settings

C.page_config()

if not C.require_auth():
    st.stop()

# --- подтянуть настройки из таблицы настроек (один раз за сессию) ---
C.pull_settings()

# --- боковая панель: название сервиса + источник данных ---
file_bytes = C.sidebar()

# --- кнопка выхода (если задан пароль) ---
try:
    _has_pw = bool(st.secrets.get("auth", {}).get("password"))  # type: ignore
except Exception:  # noqa: BLE001
    _has_pw = False
if _has_pw and st.session_state.get("_authenticated"):
    if st.sidebar.button("Выйти", key="logout"):
        st.session_state["_authenticated"] = False
        st.rerun()

# --- навигация: 4 пункта ---
nav = st.navigation([
    st.Page(posts.render, title="Проверка постов", icon="✅",
            url_path="posts", default=True),
    st.Page(holidays.render, title="Обязательные праздники", icon="🎉",
            url_path="holidays"),
    st.Page(publications.render, title="Проверка публикаций", icon="🌐",
            url_path="publications"),
    st.Page(settings.render, title="Настройки", icon="⚙️",
            url_path="settings"),
])

# --- кнопка скачивания отчёта (видна на всех страницах, если есть данные) ---
if file_bytes:
    try:
        data = C.build_app_data(file_bytes)
        C.ensure_period(data)
        period = C.current_period()
        filters = C.current_filters(data)
        filtered = C.apply_filters(data, filters, period)
        C.sidebar_download(data, filtered, period)
    except Exception:  # noqa: BLE001
        pass

nav.run()
