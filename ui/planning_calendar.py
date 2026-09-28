"""Календарь планирования постов (Streamlit + streamlit-calendar / FullCalendar).

Портированный, проверенный в браузере компонент. Работает с DataFrame постов
(колонки id, date, project, type, title) и не знает, откуда берутся данные и как
пишутся в таблицу — запись выполняет переданная функция apply_changes. Адаптер к
данным приложения — в ui/planning.py.
"""
from __future__ import annotations

import datetime as dt
import html

import pandas as pd
import streamlit as st
from streamlit_calendar import calendar

# ---------------------------------------------------------------------------
# Цвета проектов. Подобраны так, чтобы белый текст читался (контраст ≥ 4,5:1).
# Новый проект без цвета получит серый — добавьте его сюда.
# ---------------------------------------------------------------------------
PROJECT_COLORS = {
    "СМУ": "#1D4ED8",  # синий
    "ИМП": "#B91C1C",  # красный
    "МПЭ": "#047857",  # зелёный
    "МПИ": "#7E22CE",  # фиолетовый
    "АПС": "#B45309",  # охра
}
DEFAULT_COLOR = "#475569"

# Короткая метка типа поста — видна на плашке перед названием типа.
TYPE_MARKS = {
    "Отгрузка": "🚚",
    "Информационный": "ℹ",
    "Развлекательный": "☺",
    "Спецпредложение": "％",
    "Поступление": "📦",
    "Праздник": "★",
    "Поздравление": "★",
}

WEEKDAYS_RU = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS_GEN = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря"]


def _type_key(t: str) -> str:
    """«Поздравление (клиентам)» → «Поздравление»."""
    t = str(t or "").strip()
    for k in TYPE_MARKS:
        if t.lower().startswith(k.lower()):
            return k
    return t


def _is_holiday(t: str) -> bool:
    return _type_key(t) in ("Праздник", "Поздравление")


def _fmt_date(d: dt.date) -> str:
    return f"{d.day} {MONTHS_GEN[d.month - 1]} {d.year}, {WEEKDAYS_RU[d.weekday()]}"


def _normalize(posts: pd.DataFrame) -> pd.DataFrame:
    df = posts.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    if "title" not in df.columns:
        df["title"] = ""
    df["title"] = df["title"].fillna("")
    df["id"] = df["id"].astype(str)
    return df


# ---------------------------------------------------------------------------
# Стили календаря (передаются внутрь FullCalendar)
# ---------------------------------------------------------------------------
CALENDAR_CSS = """
.fc { font-family: "Source Sans Pro", "Segoe UI", sans-serif; }
.fc .fc-toolbar-title { font-size: 1.5rem; font-weight: 600; }
.fc .fc-toolbar-title::first-letter { text-transform: uppercase; }
.fc .fc-button { background: #1D4ED8; border-color: #1D4ED8; text-transform: none; }
.fc .fc-button:hover { background: #1E40AF; border-color: #1E40AF; }
.fc .fc-button:disabled { background: #93A3C4; border-color: #93A3C4; opacity: 1; }
.fc .fc-col-header-cell-cushion { color: #334155; font-weight: 600; text-transform: lowercase; }
.fc .fc-daygrid-day-number { color: #334155; font-weight: 600; }
/* выходные — лёгкий фон */
.fc .fc-day-sat, .fc .fc-day-sun { background: #F6F7F9; }
/* сегодня */
.fc .fc-day-today { background: #FFF7DB !important; }
.fc .fc-day-today .fc-daygrid-day-number { color: #92400E; }
/* плашки постов */
.fc .fc-daygrid-event { border-radius: 4px; padding: 1px 4px; margin-top: 2px; font-size: 13px; cursor: grab; }
.fc .fc-event-title { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
/* праздники — с полосой слева, чтобы выделялись среди обычных постов */
.fc .ev-holiday { box-shadow: inset 4px 0 0 #FACC15; }
/* перенесённые, но ещё не сохранённые — пунктирная рамка */
.fc .ev-moved { outline: 2px dashed #F59E0B; outline-offset: 1px; }
/* «+ещё N» */
.fc .fc-daygrid-more-link { color: #1D4ED8; font-weight: 600; }
.fc .fc-popover { box-shadow: 0 8px 24px rgba(15, 23, 42, .18); border-radius: 8px; }
.fc .fc-popover-header { background: #EEF2FF; font-weight: 600; }
"""


def _legend_html(projects: list[str]) -> str:
    chips = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin:0 14px 6px 0;font-size:14px">'
        f'<span style="width:12px;height:12px;border-radius:3px;background:{PROJECT_COLORS.get(p, DEFAULT_COLOR)}"></span>'
        f'{html.escape(p)}</span>'
        for p in projects
    )
    marks = " · ".join(f"{m} {html.escape(t)}" for t, m in TYPE_MARKS.items() if t != "Поздравление")
    return (
        f'<div style="margin:4px 0 2px">{chips}</div>'
        f'<div style="font-size:13px;color:#64748B;margin-bottom:6px">{marks} · '
        f'<span style="box-shadow:inset 4px 0 0 #FACC15;padding-left:8px">полоса слева — праздник</span></div>'
    )


def _build_events(df: pd.DataFrame, moved_ids: set[str]) -> list[dict]:
    events = []
    for r in df.itertuples():
        tkey = _type_key(r.type)
        mark = TYPE_MARKS.get(tkey, "•")
        short = f"{r.project} · {mark} {r.type}"
        color = PROJECT_COLORS.get(r.project, DEFAULT_COLOR)
        classes = []
        if _is_holiday(r.type):
            classes.append("ev-holiday")
        if r.id in moved_ids:
            classes.append("ev-moved")
        events.append({
            "id": r.id,
            "title": short,
            "start": r.date.isoformat(),
            "allDay": True,
            "backgroundColor": color,
            "borderColor": color,
            "textColor": "#FFFFFF",
            "classNames": classes,
            "extendedProps": {"project": r.project, "type": r.type, "fullTitle": r.title or short},
        })
    return events


def render_planning(posts: pd.DataFrame, apply_changes=None, source_connected: bool = True,
                    settings_page: str | None = None) -> None:
    """Рисует страницу планирования. См. описание в начале файла."""
    ss = st.session_state
    ss.setdefault("plan_pending", {})       # id -> {"id", "old_date", "new_date"}
    ss.setdefault("plan_cal_key", 0)        # меняем, чтобы сбросить календарь после «Отменить»
    ss.setdefault("plan_selected", None)

    df = _normalize(posts)

    # Спокойные серые чипы в фильтрах и синяя главная кнопка (вместо красных по умолчанию)
    st.markdown("""<style>
    [data-testid="stMultiSelect"] span[data-baseweb="tag"],
    [data-testid="stMultiSelect"] span[data-tag] { background:#E2E8F0 !important; color:#0F172A !important; }
    [data-testid="stMultiSelect"] span[data-baseweb="tag"] svg,
    [data-testid="stMultiSelect"] span[data-tag] svg { color:#475569 !important; }
    button[kind="primary"] { background:#1D4ED8; border-color:#1D4ED8; }
    button[kind="primary"]:hover { background:#1E40AF; border-color:#1E40AF; }
    </style>""", unsafe_allow_html=True)

    # --- боковая панель: заметное предупреждение про источник данных -------------
    if not source_connected:
        with st.sidebar:
            st.warning("**Google-таблица не подключена.** Переносы постов некуда сохранять. "
                       "Подключите таблицу в «Настройках» или загрузите Excel.", icon="⚠️")
            if settings_page:
                try:
                    st.page_link(settings_page, label="Открыть настройки → Источник данных", icon="⚙️")
                except Exception:  # noqa: BLE001
                    st.caption("Раздел «Настройки → Источник данных».")

    # --- применяем несохранённые переносы к отображению ---------------------------
    pending = ss.plan_pending
    view = df.copy()
    for pid, ch in pending.items():
        view.loc[view["id"] == pid, "date"] = dt.date.fromisoformat(ch["new_date"])

    # --- фильтры ----------------------------------------------------------------
    projects = sorted(view["project"].unique(), key=lambda p: list(PROJECT_COLORS).index(p)
                      if p in PROJECT_COLORS else 99)
    types = sorted({_type_key(t) for t in view["type"]})
    c1, c2 = st.columns(2)
    with c1:
        sel_projects = st.multiselect("Проекты", projects, default=projects,
                                      placeholder="Все проекты")
    with c2:
        sel_types = st.multiselect("Типы постов", types, default=types, placeholder="Все типы")
    shown = view[view["project"].isin(sel_projects or projects)
                 & view["type"].map(_type_key).isin(sel_types or types)]

    st.markdown(_legend_html(projects), unsafe_allow_html=True)

    # --- плашка несохранённых переносов ------------------------------------------
    if pending:
        with st.container(border=True):
            n = len(pending)
            word = "несохранённый перенос" if n % 10 == 1 and n % 100 != 11 else (
                "несохранённых переноса" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "несохранённых переносов")
            st.markdown(f"**Есть {n} {word}.** В таблицу они ещё не записаны — "
                        "перенесённые посты отмечены пунктирной рамкой.")
            for ch in pending.values():
                row = df[df["id"] == ch["id"]].iloc[0]
                st.markdown(f"- {row['project']} · {row['type']}: "
                            f"{_fmt_date(dt.date.fromisoformat(ch['old_date']))} → "
                            f"**{_fmt_date(dt.date.fromisoformat(ch['new_date']))}**")
            b1, b2, _ = st.columns([1, 1, 3])
            if b1.button("Применить в таблицу", type="primary", use_container_width=True,
                         disabled=not source_connected or apply_changes is None,
                         help=None if source_connected else "Сначала подключите таблицу"):
                ok = apply_changes(list(pending.values()))
                if ok:
                    ss.plan_pending = {}
                    ss.plan_cal_key += 1
                    st.toast("Изменения записаны в таблицу", icon="✅")
                    st.rerun()
                else:
                    err = ss.pop("plan_apply_error", "")
                    st.error("Не удалось записать в таблицу"
                             + (f": {err}" if err else "")
                             + ". Переносы сохранены здесь — попробуйте ещё раз.")
            if b2.button("Отменить переносы", use_container_width=True):
                ss.plan_pending = {}
                ss.plan_cal_key += 1
                st.rerun()
    else:
        st.caption("Перетащите пост на другой день — перенос появится в плашке сверху. "
                   "В таблицу он запишется только после кнопки «Применить в таблицу».")

    # --- календарь ----------------------------------------------------------------
    options = {
        "locale": "ru",
        "firstDay": 1,
        "initialView": "dayGridMonth",
        "headerToolbar": {"left": "prev", "center": "title", "right": "next"},
        "height": "auto",            # весь месяц целиком, без прокрутки внутри
        "dayMaxEvents": 4,           # остальные — «+ещё N», по клику открывается список дня
        "moreLinkText": "ещё",
        "fixedWeekCount": False,     # не добавлять лишнюю неделю следующего месяца
        "editable": source_connected,
        "eventStartEditable": source_connected,
        "eventDurationEditable": False,
        "eventDisplay": "block",
        "displayEventTime": False,
    }
    state = calendar(
        events=_build_events(shown, set(pending)),
        options=options,
        custom_css=CALENDAR_CSS,
        callbacks=["eventClick", "eventChange"],
        key=f"plan_calendar_{ss.plan_cal_key}",
    )

    # --- обработка перетаскивания и клика ---------------------------------------
    if state and state.get("callback") == "eventChange":
        ev = state["eventChange"]["event"]
        pid = str(ev["id"])
        new_date = ev["start"][:10]
        match = df.loc[df["id"] == pid, "date"]
        if not match.empty:
            orig = match.iloc[0].isoformat()
            stamp = (pid, new_date)
            if ss.get("plan_last_change") != stamp:
                ss.plan_last_change = stamp
                if new_date == orig:
                    ss.plan_pending.pop(pid, None)       # вернули на место — переноса нет
                else:
                    ss.plan_pending[pid] = {"id": pid, "old_date": orig, "new_date": new_date}
                st.rerun()
    if state and state.get("callback") == "eventClick":
        ss.plan_selected = str(state["eventClick"]["event"]["id"])

    # --- карточка выбранного поста (полное название, дата) -------------------------
    if ss.plan_selected is not None and (view["id"] == ss.plan_selected).any():
        r = view[view["id"] == ss.plan_selected].iloc[0]
        with st.container(border=True):
            st.markdown(f"**{html.escape(r['title'] or r['project'] + ' · ' + r['type'])}**")
            st.markdown(f"{r['project']} · {r['type']} · {_fmt_date(r['date'])}"
                        + (" · *перенесён, не сохранён*" if r["id"] in pending else ""))

    # --- сводка по месяцу -----------------------------------------------------------
    with st.expander("Сколько постов по проектам и типам"):
        tbl = shown.assign(Тип=shown["type"].map(_type_key)).pivot_table(
            index="project", columns="Тип", values="id", aggfunc="count", fill_value=0)
        tbl["Всего"] = tbl.sum(axis=1)
        st.dataframe(tbl.rename_axis("Проект"), use_container_width=True)
