"""Страница «Настройки»: справочник брендов, правила, белый список."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from ui_common import get_config, page_setup
from checker import config_mod

page_setup("Настройки", "⚙️")
st.title("Настройки")
st.caption("Изменения сохраняются в папку config/. После сохранения вернитесь "
           "на страницу «Загрузка» и запустите проверку заново (или перезагрузите "
           "файл), чтобы применить правила.")

tab_brands, tab_rules, tab_words = st.tabs(
    ["Бренды", "Правила и пороги", "Белый список слов"])

# ---------------------------------------------------------------------------
# Бренды
# ---------------------------------------------------------------------------
with tab_brands:
    brands = config_mod.load_brands()
    st.write("Основные контакты брендов. Хэштеги и каналы редактируйте в JSON ниже.")
    rows = []
    for code, b in brands.items():
        rows.append({
            "Код": code, "Название": b.get("name", ""),
            "Сайт": b.get("site", ""), "E-mail": b.get("email", ""),
            "Телефон": b.get("phone", ""),
        })
    edited = st.data_editor(pd.DataFrame(rows), use_container_width=True,
                            hide_index=True, key="brands_editor")

    st.markdown("**Полная настройка брендов (JSON):** хэштеги, id групп VK/OK, "
                "каналы Telegram и Max.")
    brands_json = st.text_area("brands.json", json.dumps(brands, ensure_ascii=False,
                               indent=2), height=300)

    col1, col2 = st.columns(2)
    if col1.button("💾 Сохранить бренды", type="primary"):
        try:
            data = json.loads(brands_json)
            # применить простые поля из таблицы
            for _, r in edited.iterrows():
                code = r["Код"]
                if code in data:
                    data[code]["name"] = r["Название"]
                    data[code]["site"] = r["Сайт"]
                    data[code]["email"] = r["E-mail"]
                    data[code]["phone"] = r["Телефон"]
            config_mod.save_brands(data)
            st.success("Сохранено. Запустите проверку заново.")
        except json.JSONDecodeError as e:
            st.error(f"Ошибка в JSON: {e}")
    if col2.button("↩️ Сбросить бренды к стандартным"):
        config_mod.save_brands(config_mod.get_default("brands"))
        st.success("Возвращены стандартные значения.")

# ---------------------------------------------------------------------------
# Правила
# ---------------------------------------------------------------------------
with tab_rules:
    rules = config_mod.load_rules()

    st.subheader("Включение / выключение проверок")
    toggles = rules.get("toggles", {})
    tog_rows = [{"Проверка": k, "Включена": v} for k, v in toggles.items()]
    tog_edit = st.data_editor(pd.DataFrame(tog_rows), use_container_width=True,
                              hide_index=True, key="toggles_editor",
                              column_config={"Включена": st.column_config.CheckboxColumn()})

    st.subheader("Пороги и лимиты")
    th = rules.get("thresholds", {})
    th_rows = [{"Параметр": k, "Значение": v} for k, v in th.items()]
    th_edit = st.data_editor(pd.DataFrame(th_rows), use_container_width=True,
                             hide_index=True, key="th_editor")

    st.subheader("Остальные правила (JSON)")
    st.caption("Ожидаемые площадки, словари нормализации, известные домены, "
               "фразы-остатки промтов и т.п.")
    rules_json = st.text_area("rules.json", json.dumps(rules, ensure_ascii=False,
                              indent=2), height=300)

    col1, col2 = st.columns(2)
    if col1.button("💾 Сохранить правила", type="primary"):
        try:
            data = json.loads(rules_json)
            data["toggles"] = {r["Проверка"]: bool(r["Включена"])
                               for _, r in tog_edit.iterrows()}
            new_th = {}
            for _, r in th_edit.iterrows():
                v = r["Значение"]
                try:
                    v = int(v) if float(v) == int(float(v)) else float(v)
                except (ValueError, TypeError):
                    pass
                new_th[r["Параметр"]] = v
            data["thresholds"] = new_th
            config_mod.save_rules(data)
            st.success("Сохранено. Запустите проверку заново.")
        except json.JSONDecodeError as e:
            st.error(f"Ошибка в JSON: {e}")
    if col2.button("↩️ Сбросить правила к стандартным"):
        config_mod.save_rules(config_mod.get_default("rules"))
        st.success("Возвращены стандартные значения.")

# ---------------------------------------------------------------------------
# Белый список
# ---------------------------------------------------------------------------
with tab_words:
    words = sorted(config_mod.load_whitelist())
    st.write("Слова, которые не считаются ошибками орфографии "
             "(марки стали, термины, города).")
    text = st.text_area("Одно слово на строку", "\n".join(words), height=300)
    col1, col2 = st.columns(2)
    if col1.button("💾 Сохранить белый список", type="primary"):
        config_mod.save_whitelist(text.splitlines())
        st.success("Сохранено.")
    if col2.button("↩️ Сбросить белый список"):
        config_mod.save_whitelist(config_mod.get_default("whitelist"))
        st.success("Возвращены стандартные значения.")
