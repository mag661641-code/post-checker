"""Точка входа Streamlit: загрузка файла и обзор листов.

Запуск:  streamlit run app.py
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from ui_common import (cached_load, config_signature, page_setup, run_and_store)
from checker import loader_mod

page_setup("Загрузка", "📂")

st.title("📂 Проверка постов в реестре")
st.caption("Сервис читает файл «РРП. Реестр постов/отгрузок.xlsx» и ищет ошибки. "
           "Исходный файл не изменяется — формируется отдельный отчёт.")

st.markdown(
    "**Как пользоваться:**\n"
    "1. Загрузите файл `.xlsx` ниже.\n"
    "2. Откройте слева страницы: **Сводка**, **Реестр**, **Тексты постов**, "
    "**Праздники**.\n"
    "3. При необходимости запустите **Онлайн-проверку** и скачайте отчёт на "
    "странице **Экспорт**.\n"
    "4. Справочники и правила меняются на странице **Настройки**."
)

uploaded = st.file_uploader("Выберите файл Excel (.xlsx)", type=["xlsx"])

if uploaded is not None:
    file_bytes = uploaded.getvalue()
    st.session_state["file_bytes"] = file_bytes
    st.session_state["file_name"] = uploaded.name

    try:
        wb = cached_load(file_bytes)
    except Exception as e:  # noqa: BLE001
        st.error(f"Не удалось прочитать файл: {e}")
        st.stop()

    # запустить проверки сразу
    year = dt.date.today().year
    run_and_store(file_bytes, year, None)

    st.success(f"Файл «{uploaded.name}» загружен и проверен.")

    if wb.warnings:
        with st.expander("⚠️ Замечания при чтении файла", expanded=False):
            for w in wb.warnings:
                st.write("• " + w)

    st.subheader("Найденные листы")
    expected = ([loader_mod.REGISTRY_SHEET] + loader_mod.BRAND_SHEETS
                + [loader_mod.HOLIDAYS_SHEET])
    rows = []
    for name in wb.sheet_names:
        info = wb.sheet_info.get(name, {})
        rows.append({
            "Лист": name,
            "Строк в файле": info.get("rows"),
            "Распознано записей": info.get("parsed", "—"),
            "Используется": "да" if name in expected else "нет",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    missing = [s for s in expected if s not in wb.sheet_names]
    if missing:
        st.warning("В файле не найдены ожидаемые листы: " + ", ".join(missing)
                   + ". Проверки по ним выполнены не будут.")

    st.info("Перейдите на страницу **Сводка** в меню слева. 👈")
else:
    if st.session_state.get("file_bytes"):
        st.info(f"Уже загружен файл: **{st.session_state.get('file_name')}**. "
                "Можно перейти к страницам слева или загрузить новый файл.")
