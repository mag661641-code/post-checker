"""Экран «Планирование» — фаза 1: перенос даты поста.

Показывает посты на календаре (streamlit-calendar) со всеми месяцами. Перетащил
пост на другой день → сверху появляется подтверждение переноса; по кнопке
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

    sa = C.get_service_account()
    src = config_mod.load_source()
    url = (src.get("url") or "").strip()
    is_excel = bool((st.session_state.get("sheet_source") or {}).get("is_excel"))
    can_write = bool(url and sa and not is_excel)

    _write_status(can_write, is_excel, bool(sa), bool(url))

    # бренд-фильтр
    brand_codes = list(data.cfg["brands"].keys())
    brand_sel = st.selectbox("Бренд", ["Все"] + brand_codes, key="plan_brand")

    posts = [p for p in data.posts
             if p.date and p.date_col is not None
             and (brand_sel == "Все" or p.brand == brand_sel)]
    index = {f"{p.sheet}|{p.row}": p for p in posts}

    # --- подтверждение переноса — СВЕРХУ, чтобы точно было видно ---
    _preview_and_apply(url, sa, can_write)

    st.caption("Перетащите пост на другой день — сверху появится подтверждение, "
               "затем нажмите «Применить в таблицу». Перетаскивание само по себе "
               "в таблицу не пишет. Месяцы листаются стрелками ‹ › над календарём.")

    events = _build_events(posts)
    options = {
        "editable": can_write,
        "eventStartEditable": can_write,
        "eventDurationEditable": False,
        "selectable": False,
        "initialView": "dayGridMonth",
        "initialDate": C.moscow_today().isoformat(),
        "headerToolbar": {"left": "prev,next today", "center": "title",
                          "right": ""},
        "firstDay": 1,
        "locale": "ru",
        "height": 640,
    }
    cal_key = f"plan_cal_{brand_sel}_{st.session_state.get('plan_ver', 0)}"
    state = st_calendar(events=events, options=options, key=cal_key)
    _capture_drag(state, index)


# ---------------------------------------------------------------------------
def _write_status(can_write: bool, is_excel: bool, has_sa: bool,
                  has_url: bool) -> None:
    if can_write:
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


def _build_events(posts: list[PostRecord]) -> list[dict]:
    events: list[dict] = []
    for p in posts:
        title = " · ".join(x for x in (p.brand, p.post_type) if x)
        events.append({
            "id": f"{p.sheet}|{p.row}",
            "title": title or "пост",
            "start": p.date.isoformat(),
            "allDay": True,
        })
    return events


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
    # компонент отдаёт последний перенос на каждом ререндере — реагируем только
    # на новый (иначе «Отмена» тут же перебивалась бы старым эхом)
    sig = f"{eid}|{new_date.isoformat()}"
    if st.session_state.get("plan_seen_sig") == sig:
        return
    st.session_state["plan_seen_sig"] = sig
    p = index.get(eid)
    if p is None or new_date == p.date:
        st.session_state.pop("plan_pending", None)
        return
    st.session_state["plan_pending"] = {
        "sheet": p.sheet, "row": p.row, "col": p.date_col,
        "brand": p.brand, "type": p.post_type,
        "old": p.date.isoformat(), "new": new_date.isoformat(),
    }
    st.rerun()


def _preview_and_apply(url: str, sa: Any, can_write: bool) -> None:
    pend = st.session_state.get("plan_pending")
    if not pend:
        return
    old = dt.date.fromisoformat(pend["old"])
    new = dt.date.fromisoformat(pend["new"])
    cell = sheets_write.cell_a1(pend["sheet"], pend["row"], pend["col"])
    label = " · ".join(x for x in (pend["brand"], pend["type"]) if x)

    with st.container(border=True):
        st.markdown(f"### ⬇️ Подтвердите перенос — {label}")
        st.markdown(f"**{C.fmt_date_short(old)} → {C.fmt_date_short(new)}**  ·  "
                    f"ячейка `{cell}`")
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
