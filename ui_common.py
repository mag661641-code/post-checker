"""Общие помощники для страниц Streamlit.

Здесь только связка «интерфейс ↔ модуль checker» и кеширование.
Вся логика проверок живёт в пакете checker.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd
import streamlit as st

from checker import (config_mod, loader_mod, run_all_checks, summarize)
from checker.models import Issue, Level

LEVEL_ORDER = {Level.ERROR: 0, Level.WARNING: 1, Level.ADVICE: 2, Level.TECH: 3}


def page_setup(title: str, icon: str = "📝") -> None:
    st.set_page_config(page_title=f"{title} · Проверка постов",
                       page_icon=icon, layout="wide")
    require_auth()


def require_auth() -> None:
    """Экран входа с паролем.

    Пароль берётся из секретов (`.streamlit/secrets.toml` локально или
    «Advanced settings → Secrets» в облаке):

        [auth]
        password = "ваш_пароль"

    Если пароль не задан — вход свободный (удобно при локальной разработке).
    Защита срабатывает на КАЖДОЙ странице, т.к. page_setup вызывается везде.
    """
    try:
        password = st.secrets.get("auth", {}).get("password")  # type: ignore
    except Exception:  # noqa: BLE001
        password = None

    if not password:
        return  # аутентификация не настроена — доступ открыт

    if st.session_state.get("_authenticated"):
        # кнопка выхода в боковой панели
        if st.sidebar.button("🚪 Выйти", key="logout_btn"):
            st.session_state["_authenticated"] = False
            st.rerun()
        return

    st.title("🔒 Вход")
    st.caption("Введите пароль, чтобы открыть сервис проверки постов.")
    entered = st.text_input("Пароль", type="password",
                            key="_auth_password_input")
    if st.button("Войти", type="primary"):
        if entered == password:
            st.session_state["_authenticated"] = True
            st.rerun()
        else:
            st.error("Неверный пароль. Попробуйте ещё раз.")
    st.stop()


@st.cache_data(show_spinner="Читаем файл…")
def cached_load(file_bytes: bytes) -> "loader_mod.LoadedWorkbook":
    return loader_mod.load_workbook(file_bytes)


@st.cache_data(show_spinner="Проверяем посты…")
def cached_checks(file_bytes: bytes, cfg_signature: str,
                  today_iso: str, year: int, month: int | None):
    wb = cached_load(file_bytes)
    cfg = get_config()
    today = dt.date.fromisoformat(today_iso)
    return run_all_checks(wb, cfg, today=today, holiday_year=year,
                          holiday_month=month)


def get_config() -> dict[str, Any]:
    """Загрузить конфигурацию (кешируется в session_state, чтобы совпадала
    с только что сохранёнными настройками)."""
    return config_mod.load_all()


def config_signature() -> str:
    """Строка-подпись конфигурации для инвалидации кеша при изменении настроек."""
    import json
    cfg = get_config()
    return json.dumps({"b": cfg["brands"], "r": cfg["rules"],
                       "w": sorted(cfg["whitelist"])}, ensure_ascii=False,
                      sort_keys=True)


def require_file() -> bytes | None:
    """Вернуть загруженный файл из session_state или показать подсказку."""
    data = st.session_state.get("file_bytes")
    if not data:
        st.info("Сначала загрузите файл на странице **Загрузка**.")
        return None
    return data


def all_issues_from_state() -> list[Issue]:
    res = st.session_state.get("results") or {}
    return (res.get("registry", []) + res.get("text", [])
            + res.get("holiday", []) + st.session_state.get("online_issues", []))


def run_and_store(file_bytes: bytes, year: int, month: int | None) -> None:
    res = cached_checks(file_bytes, config_signature(),
                        dt.date.today().isoformat(), year, month)
    st.session_state["results"] = res


def issues_to_df(issues: list[Issue]) -> pd.DataFrame:
    rows = []
    for i in issues:
        rows.append({
            "Уровень": f"{i.level.emoji} {i.level.title_ru}",
            "_lvl": LEVEL_ORDER.get(i.level, 9),
            "Лист": i.sheet,
            "Строка": i.row,
            "Колонка": i.column,
            "Бренд": i.brand,
            "Тип поста": i.post_type,
            "Статус": i.status,
            "Суть замечания": i.message,
            "Как исправить": i.fix,
            "Ссылка": i.link,
            "Код": i.code,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["_lvl", "Лист", "Строка"]).drop(columns=["_lvl"])
    return df


def level_filter_widget(key: str) -> set[Level]:
    labels = {"🔴 Ошибки": Level.ERROR, "🟡 Предупреждения": Level.WARNING,
              "🔵 Советы": Level.ADVICE, "⚙️ Технические": Level.TECH}
    chosen = st.multiselect("Уровень замечаний", list(labels.keys()),
                            default=list(labels.keys())[:3], key=key)
    return {labels[c] for c in chosen}
