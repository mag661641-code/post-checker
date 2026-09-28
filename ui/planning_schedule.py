"""Режим «Составить график» (фаза 2a) — черновой график по правилам.

Ничего в Google-таблицу НЕ пишет: раскладывает черновые слоты (дата + проект +
тип) по правилам на выбранный месяц и показывает их на календаре пунктиром.
Правила: для каждого проекта — дни недели, чередование рубрик, пропуск
праздников. Готовые слоты потом (шаг 2b) можно будет записать в таблицу.
"""
from __future__ import annotations

import calendar as _cal
import datetime as dt
from typing import Any

import pandas as pd
import streamlit as st
from streamlit_calendar import calendar as st_calendar

from checker import normalize as N
from ui import common as C
from ui.planning_calendar import (PROJECT_COLORS, DEFAULT_COLOR, TYPE_MARKS,
                                   WEEKDAYS_RU, _type_key, _is_holiday, _fmt_date)

# рубрики по умолчанию для выбора (можно выбрать любые из встреченных в таблице)
_DEFAULT_TYPES = ["Информационный", "Развлекательный", "Отгрузка",
                  "Спецпредложение", "Поступление"]

_SCHEDULE_CSS = """
.fc .ev-draft { outline: 2px dashed #64748B; outline-offset: 1px; }
.fc .fc-daygrid-event { border-radius: 4px; padding: 1px 4px; margin-top: 2px; font-size: 13px; }
.fc .fc-day-sat, .fc .fc-day-sun { background: #F6F7F9; }
.fc .fc-toolbar-title { font-size: 1.4rem; font-weight: 600; }
.fc .fc-toolbar-title::first-letter { text-transform: uppercase; }
.fc .fc-button { background: #1D4ED8; border-color: #1D4ED8; text-transform: none; }
"""


# ---------------------------------------------------------------------------
# Генерация слотов (чистая функция — тестируется отдельно)
# ---------------------------------------------------------------------------
def generate_slots(rules: dict[str, dict], year: int, month: int,
                   holidays: set[dt.date]) -> list[dict]:
    """Разложить черновые слоты по правилам.

    rules[project] = {"weekdays": [0..6], "types": [str, ...],
                      "skip_holidays": bool}. Тип назначается по кругу из types
    в порядке дат. Возвращает список {id, date, project, type}.
    """
    slots: list[dict] = []
    ndays = _cal.monthrange(year, month)[1]
    counters = {p: 0 for p in rules}
    for day in range(1, ndays + 1):
        d = dt.date(year, month, day)
        for project, r in rules.items():
            if d.weekday() not in r.get("weekdays", []):
                continue
            if r.get("skip_holidays") and d in holidays:
                continue
            types = r.get("types") or [""]
            t = types[counters[project] % len(types)]
            counters[project] += 1
            slots.append({"id": f"draft|{project}|{d.isoformat()}",
                          "date": d, "project": project, "type": t})
    return slots


def _holiday_dates(data: "C.AppData") -> set[dt.date]:
    out: set[dt.date] = set()
    for h in getattr(data.wb, "holidays_raw", []) or []:
        d, _ = N.parse_date(h.get("date_raw"))
        if d:
            out.add(d)
    return out


def _draft_events(slots: list[dict], overrides: dict[str, str]) -> list[dict]:
    events = []
    for s in slots:
        d = dt.date.fromisoformat(overrides[s["id"]]) if s["id"] in overrides else s["date"]
        color = PROJECT_COLORS.get(s["project"], DEFAULT_COLOR)
        mark = TYPE_MARKS.get(_type_key(s["type"]), "•")
        events.append({
            "id": s["id"],
            "title": f"✎ {s['project']} · {mark} {s['type']}",
            "start": d.isoformat(),
            "allDay": True,
            "backgroundColor": color,
            "borderColor": color,
            "textColor": "#FFFFFF",
            "classNames": ["ev-draft"],
            "editable": True,
        })
    return events


def _existing_events(df: pd.DataFrame, year: int, month: int) -> list[dict]:
    """Уже существующие посts месяца — приглушённым фоном, без перетаскивания."""
    events = []
    for r in df.itertuples():
        if r.date.year != year or r.date.month != month:
            continue
        color = PROJECT_COLORS.get(r.project, DEFAULT_COLOR)
        events.append({
            "id": f"exist|{r.id}",
            "title": f"{r.project} · {r.type}",
            "start": r.date.isoformat(),
            "allDay": True,
            "backgroundColor": color,
            "borderColor": color,
            "textColor": "#FFFFFF",
            "editable": False,
            "display": "background",
        })
    return events


# ---------------------------------------------------------------------------
# Экран
# ---------------------------------------------------------------------------
def render(data: "C.AppData", df: pd.DataFrame, source_connected: bool) -> None:
    ss = st.session_state
    ss.setdefault("sched_rules", {})
    ss.setdefault("sched_slots", [])
    ss.setdefault("sched_overrides", {})
    ss.setdefault("sched_cal_key", 0)

    brands = list(data.cfg["brands"].keys())
    types_seen = sorted({p.post_type for p in data.posts if p.post_type})
    type_options = list(dict.fromkeys(_DEFAULT_TYPES + types_seen))

    today = C.moscow_today()
    nxt = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1)

    st.markdown("Задайте правила по проектам, выберите месяц и нажмите «Составить "
                "черновик». Черновые посты появятся на календаре пунктиром — в "
                "таблицу они пока не записываются.")

    # --- выбор месяца ---
    c1, c2 = st.columns(2)
    year = c1.selectbox("Год", [today.year, today.year + 1],
                        index=(0 if nxt.year == today.year else 1), key="sched_year")
    month = c2.selectbox("Месяц", list(range(1, 13)), index=nxt.month - 1,
                         format_func=lambda m: C.MONTHS_NOM[m], key="sched_month")

    # --- правила по проектам ---
    st.subheader("Правила по проектам")
    rules: dict[str, dict] = {}
    for b in brands:
        saved = ss.sched_rules.get(b, {})
        with st.expander(f"{b}", expanded=False):
            wd_labels = st.multiselect(
                "Дни недели", WEEKDAYS_RU,
                default=[WEEKDAYS_RU[i] for i in saved.get("weekdays", [])],
                key=f"sched_wd_{b}")
            tsel = st.multiselect(
                "Рубрики (чередуются по кругу)", type_options,
                default=saved.get("types", []), key=f"sched_types_{b}")
            skip = st.checkbox("Пропускать обязательные праздники",
                               value=saved.get("skip_holidays", True),
                               key=f"sched_skip_{b}")
        weekdays = [WEEKDAYS_RU.index(x) for x in wd_labels]
        if weekdays:
            rules[b] = {"weekdays": weekdays, "types": tsel, "skip_holidays": skip}

    b1, b2 = st.columns([1, 1])
    if b1.button("Составить черновик", type="primary", use_container_width=True,
                 disabled=not rules):
        ss.sched_rules = rules
        ss.sched_slots = generate_slots(rules, int(year), int(month),
                                        _holiday_dates(data))
        ss.sched_overrides = {}
        ss.sched_cal_key += 1
        st.rerun()
    if b2.button("Очистить черновик", use_container_width=True,
                 disabled=not ss.sched_slots):
        ss.sched_slots = []
        ss.sched_overrides = {}
        ss.sched_cal_key += 1
        st.rerun()

    if not ss.sched_slots:
        if not rules:
            st.info("Пока не заданы правила: выберите хотя бы один день недели у "
                    "проекта.")
        return

    # --- сводка ---
    n = len(ss.sched_slots)
    st.success(f"Черновик: {n} постов на {C.MONTHS_NOM[int(month)].lower()} "
               f"{int(year)}. Двигайте посты на календаре, если нужно поправить дни.")

    # --- календарь черновика ---
    options = {
        "locale": "ru",
        "firstDay": 1,
        "initialView": "dayGridMonth",
        "initialDate": dt.date(int(year), int(month), 1).isoformat(),
        "headerToolbar": {"left": "prev", "center": "title", "right": "next"},
        "height": "auto",
        "fixedWeekCount": False,
        "dayMaxEvents": 5,
        "moreLinkText": "ещё",
        "editable": True,
        "eventDurationEditable": False,
        "eventDisplay": "block",
        "displayEventTime": False,
    }
    events = _existing_events(df, int(year), int(month)) + \
        _draft_events(ss.sched_slots, ss.sched_overrides)
    state = st_calendar(events=events, options=options, custom_css=_SCHEDULE_CSS,
                        callbacks=["eventChange"],
                        key=f"sched_cal_{ss.sched_cal_key}")

    # --- перенос черновых слотов ---
    if state and state.get("callback") == "eventChange":
        ev = state["eventChange"]["event"]
        sid = str(ev["id"])
        new_date = ev["start"][:10]
        stamp = (sid, new_date)
        if sid.startswith("draft|") and ss.get("sched_last_change") != stamp:
            ss.sched_last_change = stamp
            ss.sched_overrides[sid] = new_date
            st.rerun()

    # --- запись в таблицу — следующий шаг (2b) ---
    st.divider()
    st.button("Записать график в таблицу", disabled=True,
              help="Будет на следующем шаге (2b): вставка строк с сохранением "
                   "оформления. Пока черновик только показывается.")
    st.caption("Запись новых строк в таблицу появится следующим шагом — сначала "
               "обкатаем раскладку графика.")
