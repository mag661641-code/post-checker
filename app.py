"""Точка входа Streamlit: загрузка реестра (Google-таблица или файл) и обзор листов.

Запуск:  streamlit run app.py
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from ui_common import (cached_load, config_signature, page_setup, run_and_store)
from checker import loader_mod, gsheets

page_setup("Загрузка")

st.title("Проверка постов в реестре")
st.caption("Сервис читает реестр «РРП. Реестр постов/отгрузок» и ищет ошибки. "
           "Исходные данные не изменяются — формируется отдельный отчёт.")


def process(file_bytes: bytes, name: str) -> None:
    """Прочитать данные, запустить проверки и показать сводку по листам."""
    st.session_state["file_bytes"] = file_bytes
    st.session_state["file_name"] = name
    try:
        wb = cached_load(file_bytes)
    except Exception as e:  # noqa: BLE001
        st.error(f"Не удалось прочитать данные: {e}")
        st.stop()

    year = dt.date.today().year
    run_and_store(file_bytes, year, None)
    st.success(f"«{name}» загружено и проверено.")

    if wb.warnings:
        with st.expander("Замечания при чтении", expanded=False):
            for w in wb.warnings:
                st.write("• " + w)

    st.subheader("Найденные листы")
    expected = ([loader_mod.REGISTRY_SHEET] + loader_mod.BRAND_SHEETS
                + [loader_mod.HOLIDAYS_SHEET])
    rows = []
    for sheet in wb.sheet_names:
        info = wb.sheet_info.get(sheet, {})
        rows.append({
            "Лист": sheet,
            "Строк в файле": info.get("rows"),
            "Распознано записей": info.get("parsed", "—"),
            "Используется": "да" if sheet in expected else "нет",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    missing = [s for s in expected if s not in wb.sheet_names]
    if missing:
        st.warning("Не найдены ожидаемые листы: " + ", ".join(missing)
                   + ". Проверки по ним выполнены не будут.")
    st.info("Перейдите на страницу «Сводка» в меню слева.")


def _get_service_account():
    """Ключ сервисного аккаунта из секретов: таблица или строка с JSON."""
    try:
        if "gcp_service_account" in st.secrets:            # type: ignore
            return st.secrets["gcp_service_account"]        # type: ignore
        if "gcp_service_account_json" in st.secrets:        # type: ignore
            return st.secrets["gcp_service_account_json"]   # type: ignore
    except Exception:  # noqa: BLE001
        pass
    return None


# --- основной способ: Google-таблица ---
st.subheader("Загрузка из Google-таблицы")
sa_info = _get_service_account()

if sa_info is None:
    st.warning("Ключ сервисного аккаунта не задан. Добавьте его в "
               "Settings → Advanced settings → Secrets (см. README).")

default_url = st.session_state.get("gsheet_url", "")
url = st.text_input("Ссылка на Google-таблицу", value=default_url,
                    placeholder="https://docs.google.com/spreadsheets/d/…")
if st.button("Загрузить из Google", type="primary", disabled=sa_info is None):
    if not url.strip():
        st.error("Вставьте ссылку на Google-таблицу.")
    else:
        st.session_state["gsheet_url"] = url
        try:
            with st.spinner("Скачиваем таблицу из Google…"):
                data = gsheets.download_as_xlsx(url, sa_info)
        except Exception as e:  # noqa: BLE001
            st.error(f"Не удалось получить таблицу из Google: {e}")
            st.stop()
        process(data, "Google-таблица")

if st.session_state.get("file_bytes"):
    st.divider()
    st.caption(f"Сейчас загружено: {st.session_state.get('file_name')}. "
               "Можно перейти к страницам слева.")

# --- запасной способ: файл (в боковой панели, чтобы не мешать основному) ---
st.sidebar.divider()
st.sidebar.subheader("Загрузить файл")
uploaded = st.sidebar.file_uploader("Файл Excel (.xlsx)", type=["xlsx"])
if uploaded is not None:
    process(uploaded.getvalue(), uploaded.name)
