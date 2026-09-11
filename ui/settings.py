"""Экран «Настройки»: бренды, типы/соцсети, словарь орфографии,
скрытые замечания, пороги и лимиты."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from checker import config_mod, gsheets, loader_mod
from ui import common as C


def render() -> None:
    st.title("Настройки")

    tabs = st.tabs(["🔗 Источник данных", "Бренды", "Типы постов и соцсети",
                    "Словарь орфографии", "Скрытые замечания", "Пороги и лимиты"])
    with tabs[0]:
        _source()
    with tabs[1]:
        _brands()
    with tabs[2]:
        _types_socials()
    with tabs[3]:
        _whitelist()
    with tabs[4]:
        _ignored()
    with tabs[5]:
        _thresholds()


def _source() -> None:
    src = config_mod.load_source()
    sa = C.get_service_account()

    st.subheader("Ссылка на Google-таблицу")

    url = st.text_input("Ссылка на таблицу «РРП. Реестр постов/отгрузок»",
                        value=src.get("url", ""), key="src_url",
                        placeholder="https://docs.google.com/spreadsheets/d/…")

    c1, c2 = st.columns([1, 1])
    if c1.button("💾 Сохранить", key="src_save", type="primary"):
        config_mod.save_source({"method": "service_account",
                                "url": url.strip(), "refresh_minutes": 0,
                                "gids": {}})
        C.clear_source_cache()
        st.toast("Ссылка сохранена")
        st.rerun()
    if c2.button("Проверить подключение", key="src_test"):
        expected = [loader_mod.REGISTRY_SHEET] + loader_mod.BRAND_SHEETS
        with st.spinner("Проверяем…"):
            res = gsheets.test_connection(url, "service_account", sa, expected)
        if res["ok"]:
            parts = ", ".join(f"{s['title']} — {s['rows']} строк"
                              for s in res["sheets"][:6] if s.get("rows"))
            st.success(f"Подключено: «{res['title']}», листов: "
                       f"{len(res['sheets'])}. {parts}")
        else:
            st.error(res["message"])
            if res["error"] == "no_access" and res.get("sa_email"):
                st.code(res["sa_email"], language=None)

    st.caption("Свежие правки из таблицы подтягиваются кнопкой «🔄 Обновить "
               "данные» в панели слева.")


def _clear_caches() -> None:
    C.cached_base_checks.clear()
    C.cached_spell.clear()


def _brands() -> None:
    brands = config_mod.load_brands()
    rows = [{"Код": c, "Название": b.get("name", ""), "Сайт": b.get("site", ""),
             "E-mail": b.get("email", ""), "Телефон": b.get("phone", "")}
            for c, b in brands.items()]
    edited = st.data_editor(pd.DataFrame(rows), use_container_width=True,
                            hide_index=True, key="s_brands")
    st.caption("Хэштеги, id групп и каналы — в полном JSON ниже.")
    txt = st.text_area("brands.json", json.dumps(brands, ensure_ascii=False,
                       indent=2), height=260, key="s_brands_json")
    c1, c2 = st.columns(2)
    if c1.button("Сохранить", key="s_brands_save", type="primary"):
        try:
            data = json.loads(txt)
            for _, r in edited.iterrows():
                code = r["Код"]
                if code in data:
                    data[code].update({"name": r["Название"], "site": r["Сайт"],
                                       "email": r["E-mail"], "phone": r["Телефон"]})
            config_mod.save_brands(data)
            _clear_caches()
            st.success("Сохранено.")
        except json.JSONDecodeError as e:
            st.error(f"Ошибка в JSON: {e}")
    if c2.button("Вернуть стандартные", key="s_brands_reset"):
        config_mod.save_brands(config_mod.get_default("brands"))
        _clear_caches()
        st.success("Возвращены стандартные значения.")


def _types_socials() -> None:
    rules = config_mod.load_rules()
    st.write("Словари приведения написаний к эталону (тип поста, соцсеть).")
    types_json = st.text_area(
        "Типы постов (эталон → варианты написания)",
        json.dumps(rules.get("post_type_canonical", {}), ensure_ascii=False,
                   indent=2), height=200, key="s_types")
    soc_json = st.text_area(
        "Соцсети (эталон → варианты написания)",
        json.dumps(rules.get("social_canonical", {}), ensure_ascii=False,
                   indent=2), height=200, key="s_soc")
    c1, c2 = st.columns(2)
    if c1.button("Сохранить", key="s_types_save", type="primary"):
        try:
            rules["post_type_canonical"] = json.loads(types_json)
            rules["social_canonical"] = json.loads(soc_json)
            config_mod.save_rules(rules)
            _clear_caches()
            st.success("Сохранено.")
        except json.JSONDecodeError as e:
            st.error(f"Ошибка в JSON: {e}")
    if c2.button("Вернуть стандартные", key="s_types_reset"):
        config_mod.save_rules(config_mod.get_default("rules"))
        _clear_caches()
        st.success("Возвращены стандартные значения.")


def _whitelist() -> None:
    words = sorted(config_mod.load_whitelist())
    st.write("Слова, которые не считаются ошибками орфографии.")
    txt = st.text_area("Одно слово на строку", "\n".join(words), height=320,
                       key="s_wl")
    c1, c2 = st.columns(2)
    if c1.button("Сохранить", key="s_wl_save", type="primary"):
        config_mod.save_whitelist(txt.splitlines())
        _clear_caches()
        st.success("Сохранено.")
    if c2.button("Вернуть стандартные", key="s_wl_reset"):
        config_mod.save_whitelist(config_mod.get_default("whitelist"))
        _clear_caches()
        st.success("Возвращены стандартные значения.")


def _ignored() -> None:
    data = config_mod.load_ignored()
    if not data:
        st.info("Скрытых замечаний нет. Кнопка «Не ошибка» в карточке поста "
                "добавляет замечания сюда.")
        return
    st.write("Замечания, помеченные как «не ошибка». Их можно вернуть.")
    for key, info in list(data.items()):
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"Лист «{info.get('sheet')}», строка {info.get('row')} — "
                    f"проверка `{info.get('code')}`")
        if c2.button("Вернуть", key=f"unig_{key}"):
            config_mod.remove_ignored(key)
            _clear_caches()
            st.rerun()


def _thresholds() -> None:
    rules = config_mod.load_rules()
    th = rules.get("thresholds", {})
    rows = [{"Параметр": k, "Значение": v} for k, v in th.items()]
    edited = st.data_editor(pd.DataFrame(rows), use_container_width=True,
                            hide_index=True, key="s_th")
    st.caption("Ожидаемые площадки, известные домены и прочее — в полном JSON "
               "на странице ниже.")
    rules_json = st.text_area("rules.json (всё остальное)",
                              json.dumps(rules, ensure_ascii=False, indent=2),
                              height=240, key="s_rules_json")
    c1, c2 = st.columns(2)
    if c1.button("Сохранить", key="s_th_save", type="primary"):
        try:
            data = json.loads(rules_json)
            new_th = {}
            for _, r in edited.iterrows():
                v = r["Значение"]
                try:
                    v = int(v) if float(v) == int(float(v)) else float(v)
                except (ValueError, TypeError):
                    pass
                new_th[r["Параметр"]] = v
            data["thresholds"] = new_th
            config_mod.save_rules(data)
            _clear_caches()
            st.success("Сохранено.")
        except json.JSONDecodeError as e:
            st.error(f"Ошибка в JSON: {e}")
    if c2.button("Вернуть стандартные", key="s_th_reset"):
        config_mod.save_rules(config_mod.get_default("rules"))
        _clear_caches()
        st.success("Возвращены стандартные значения.")
