"""Экран «Планирование» — календарь постов с переносом даты.

Тонкий адаптер: собирает посты приложения в DataFrame и передаёт их
проверенному компоненту календаря (ui.planning_calendar). Запись переносов в
Google-таблицу идёт через существующий checker.sheets_write.set_date — формат
данных и способ записи не меняются.
"""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from checker import config_mod, sheets_write
from ui import common as C


def render() -> None:
    st.title("Планирование")

    file_bytes = st.session_state.get("file_bytes")
    if not file_bytes:
        C.empty_no_file()
        return

    try:
        from ui import planning_calendar as PC
    except Exception:  # noqa: BLE001
        st.error("Не установлен компонент календаря. Добавьте в requirements.txt "
                 "строку `streamlit-calendar`, установите зависимости и "
                 "перезапустите приложение.")
        return

    data = C.build_app_data(file_bytes)

    sa = C.get_service_account()
    src = config_mod.load_source()
    url = (src.get("url") or "").strip()
    is_excel = bool((st.session_state.get("sheet_source") or {}).get("is_excel"))
    source_connected = bool(url and sa and not is_excel)

    # --- посты приложения → DataFrame для календаря ---
    rows: list[dict] = []
    date_col_by_id: dict[str, int] = {}
    for p in data.posts:
        if not p.date or p.date_col is None:
            continue
        eid = f"{p.sheet}|{p.row}"
        date_col_by_id[eid] = p.date_col
        title = (p.text or "").strip().splitlines()[0][:120] if p.text else ""
        rows.append({"id": eid, "date": p.date, "project": p.brand,
                     "type": p.post_type or "", "title": title})

    if not rows:
        st.info("На листах брендов нет постов с датой — планировать нечего.")
        return

    df = pd.DataFrame(rows, columns=["id", "date", "project", "type", "title"])

    # --- режим: готовый календарь или составление графика по правилам ---
    mode = st.radio("Режим", ["Календарь", "Составить график"],
                    horizontal=True, label_visibility="collapsed", key="plan_mode")
    if mode == "Составить график":
        from ui import planning_schedule as PS
        PS.render(data, df, source_connected)
        return

    def _apply(changes: list[dict]) -> bool:
        """Записать переносы в таблицу. True — если всё записалось.

        При ошибке возвращаем False и сохраняем текст ошибки: компонент оставит
        переносы на месте, чтобы можно было повторить.
        """
        try:
            for ch in changes:
                sheet, row = ch["id"].split("|", 1)
                col = date_col_by_id.get(ch["id"])
                if col is None:
                    continue
                sheets_write.set_date(url, sheet, int(row), col,
                                      dt.date.fromisoformat(ch["new_date"]), sa)
            C.fetch_source(force=True)  # перечитать таблицу, чтобы даты обновились
            return True
        except Exception as e:  # noqa: BLE001
            st.session_state["plan_apply_error"] = str(e)
            return False

    PC.render_planning(df, apply_changes=_apply,
                       source_connected=source_connected, settings_page="settings")
