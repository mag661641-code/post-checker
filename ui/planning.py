"""Экран «Планирование» — фаза 1: перенос даты поста.

Показывает посты выбранного месяца/бренда на календаре (streamlit-calendar).
Перетаскивание события на другой день формирует предпросмотр переноса; по кнопке
«Применить» новая дата записывается в верхнюю ячейку блока поста в Google-таблице
(checker.sheets_write). Меняется только значение даты — оформление и объединённые
ячейки не трогаются. Строка поста физически не пересортировывается.

Запись возможна только для Google-таблицы через сервисный аккаунт с «Редактором».
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

import streamlit as st

from checker import config_mod, sheets_write
from checker.models import PostRecord
from ui import common as C


def render() -> None:
    st.title("Планирование")

    file_bytes = st.session_state.get("file_bytes")
    if not file_bytes:
        C.empty_no_file()
        return

    try:
        from streamlit_calendar import calendar as st_calendar
    except Exception:  # noqa: BLE001
        st.error("Не установлен компонент календаря. Добавьте в requirements.txt "
                 "строку `streamlit-calendar`, установите зависимости и "
                 "перезапустите приложение.")
        return

    data = C.build_app_data(file_bytes)
    C.ensure_period(data)

    sa = C.get_service_account()
    src = config_mod.load_source()
    url = (src.get("url") or "").strip()
    is_excel = bool((st.session_state.get("sheet_source") or {}).get("is_excel"))
    can_write = bool(url and sa and not is_excel)

    _write_status(can_write, is_excel, bool(sa), bool(url))

    # выбор месяца и бренда
    C.month_selector(data, key_prefix="plan")
    period = C.current_period()
    brand_codes = list(data.cfg["brands"].keys())
    brand_sel = st.selectbox("Бренд", ["Все"] + brand_codes, key="plan_brand")

    posts = [p for p in C.posts_in_period(data, period)
             if p.date and p.date_col is not None
             and (brand_sel == "Все" or p.brand == brand_sel)]

    st.caption("Перетащите пост на другой день, затем нажмите «Применить в "
               "таблицу». Записывается только дата — текст и оформление не "
               "меняются, порядок строк в таблице остаётся прежним.")

    events, index = _build_events(posts)
    initial = (dt.date(*period, 1) if isinstance(period, tuple)
               else C.moscow_today())
    options = {
        "editable": can_write,
        "eventStartEditable": can_write,
        "eventDurationEditable": False,
        "selectable": False,
        "initialView": "dayGridMonth",
        "initialDate": initial.isoformat(),
        "headerToolbar": {"left": "", "center": "title", "right": ""},
        "firstDay": 1,
        "locale": "ru",
        "height": 640,
    }
    # ключ включает выбор и версию: иначе компонент не обновит события после записи
    cal_key = f"plan_cal_{brand_sel}_{period}_{st.session_state.get('plan_ver', 0)}"
    state = st_calendar(events=events, options=options, key=cal_key)

    _capture_drag(state, index)
    _preview_and_apply(url, sa, can_write)


# ---------------------------------------------------------------------------
def _write_status(can_write: bool, is_excel: bool, has_sa: bool,
                  has_url: bool) -> None:
    if can_write:
        st.success("✅ Запись в Google-таблицу доступна.")
        return
    if is_excel:
        st.warning("Открыт загруженный Excel-файл — запись возможна только для "
                   "подключённой Google-таблицы.")
    elif not has_url:
        st.warning("Не задана ссылка на таблицу — укажите её в «Настройки → "
                   "Источник данных».")
    elif not has_sa:
        st.warning("Для записи нужен сервисный аккаунт с доступом «Редактор» "
                   "к таблице (ключ добавляется в секреты).")


def _build_events(posts: list[PostRecord]) -> tuple[list[dict], dict[str, PostRecord]]:
    events: list[dict] = []
    index: dict[str, PostRecord] = {}
    for p in posts:
        eid = f"{p.sheet}|{p.row}"
        index[eid] = p
        title = " · ".join(x for x in (p.brand, p.post_type) if x)
        events.append({
            "id": eid,
            "title": title or "пост",
            "start": p.date.isoformat(),
            "allDay": True,
        })
    return events, index


def _event_start(state: Any) -> Optional[tuple[str, dt.date]]:
    """Достать (id события, новая дата) из ответа календаря о перетаскивании."""
    if not isinstance(state, dict):
        return None
    change = state.get("eventChange") or state.get("eventDrop")
    if not isinstance(change, dict):
        return None
    ev = change.get("event") or {}
    eid = ev.get("id")
    start = ev.get("start")
    if not eid or not start:
        return None
    try:
        new_date = dt.date.fromisoformat(str(start)[:10])
    except ValueError:
        return None
    return eid, new_date


def _capture_drag(state: Any, index: dict[str, PostRecord]) -> None:
    parsed = _event_start(state)
    if not parsed:
        return
    eid, new_date = parsed
    p = index.get(eid)
    if p is None or new_date == p.date:
        return
    st.session_state["plan_pending"] = {
        "sheet": p.sheet, "row": p.row, "col": p.date_col,
        "brand": p.brand, "type": p.post_type,
        "old": p.date.isoformat(), "new": new_date.isoformat(),
    }


def _preview_and_apply(url: str, sa: Any, can_write: bool) -> None:
    pend = st.session_state.get("plan_pending")
    if not pend:
        return
    old = dt.date.fromisoformat(pend["old"])
    new = dt.date.fromisoformat(pend["new"])
    cell = sheets_write.cell_a1(pend["sheet"], pend["row"], pend["col"])
    label = " · ".join(x for x in (pend["brand"], pend["type"]) if x)

    st.divider()
    st.markdown(f"**Перенос поста** — {label}")
    st.info(f"{C.fmt_date_short(old)} → {C.fmt_date_short(new)}  ·  ячейка {cell}")

    c1, c2 = st.columns(2)
    if c1.button("✅ Применить в таблицу", type="primary",
                 disabled=not can_write, use_container_width=True):
        try:
            with st.spinner("Записываю дату в таблицу…"):
                sheets_write.set_date(url, pend["sheet"], pend["row"],
                                      pend["col"], new, sa)
        except Exception as e:  # noqa: BLE001
            st.error(f"Не удалось записать в таблицу: {e}")
            return
        st.session_state.pop("plan_pending", None)
        st.session_state["plan_ver"] = st.session_state.get("plan_ver", 0) + 1
        with st.spinner("Обновляю данные из таблицы…"):
            C.fetch_source(force=True)
        st.toast("Дата обновлена в таблице")
        st.rerun()

    if c2.button("Отмена", use_container_width=True):
        st.session_state.pop("plan_pending", None)
        st.rerun()
