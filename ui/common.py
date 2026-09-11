"""Общие помощники интерфейса: даты и месяцы, загрузка данных, фильтры,
выбор месяца, боковая панель, экспорт, кеш орфографии.

Логика проверок здесь не дублируется — только связка с пакетом checker.
"""
from __future__ import annotations

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from checker import (config_mod, loader_mod, registry_checks, report_mod,
                     summarize, text_checks, speller)
from checker import normalize as N
from checker.models import Issue, Level, PostRecord, RegistryRow

# ---------------------------------------------------------------------------
# Месяцы, дни недели, даты
# ---------------------------------------------------------------------------
MONTHS_NOM = {1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель", 5: "Май",
              6: "Июнь", 7: "Июль", 8: "Август", 9: "Сентябрь", 10: "Октябрь",
              11: "Ноябрь", 12: "Декабрь"}
MONTHS_GEN = {1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая",
              6: "июня", 7: "июля", 8: "августа", 9: "сентября", 10: "октября",
              11: "ноября", 12: "декабря"}
WEEKDAYS_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
WEEKDAYS_FULL = ["понедельник", "вторник", "среда", "четверг", "пятница",
                 "суббота", "воскресенье"]

LEVEL_LABELS = {Level.ERROR: "🔴 Ошибки", Level.WARNING: "🟡 Предупреждения",
                Level.ADVICE: "🔵 Советы"}


def moscow_today() -> dt.date:
    return dt.datetime.now(ZoneInfo("Europe/Moscow")).date()


def fmt_month(year: int, month: int) -> str:
    return f"{MONTHS_NOM[month]} {year}"


def fmt_month_lower(year: int, month: int) -> str:
    return f"{MONTHS_NOM[month].lower()} {year}"


def fmt_date_short(d: Optional[dt.date]) -> str:
    if not d:
        return ""
    return f"{d:%d.%m.%Y}, {WEEKDAYS_SHORT[d.weekday()]}"


def fmt_date_full(d: Optional[dt.date]) -> str:
    if not d:
        return "Дата не указана"
    return f"{d.day} {MONTHS_GEN[d.month]} {d.year}, {WEEKDAYS_FULL[d.weekday()]}"


def norm_type(value: str, rules: dict) -> str:
    """Нормализовать тип поста для показа (Информативый → Информационный)."""
    canon, _ = N.canonical_post_type(value, rules.get("post_type_canonical", {}))
    return canon or (value or "")


# ---------------------------------------------------------------------------
# Настройка страницы и вход по паролю
# ---------------------------------------------------------------------------
def page_config() -> None:
    st.set_page_config(page_title="Проверка постов", page_icon="✅",
                       layout="wide")


def require_auth() -> bool:
    """Экран входа с паролем. Возвращает True, если доступ разрешён."""
    try:
        password = st.secrets.get("auth", {}).get("password")  # type: ignore
    except Exception:  # noqa: BLE001
        password = None
    if not password:
        return True
    if st.session_state.get("_authenticated"):
        return True
    st.title("Вход")
    st.caption("Введите пароль, чтобы открыть сервис.")
    entered = st.text_input("Пароль", type="password", key="_auth_pw")
    if st.button("Войти", type="primary"):
        if entered == password:
            st.session_state["_authenticated"] = True
            st.rerun()
        else:
            st.error("Неверный пароль. Попробуйте ещё раз.")
    return False


# ---------------------------------------------------------------------------
# Загрузка данных и проверки
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner="Читаем данные…")
def cached_load(file_bytes: bytes) -> loader_mod.LoadedWorkbook:
    return loader_mod.load_workbook(file_bytes)


def _config_signature(cfg: dict) -> str:
    import json
    return json.dumps({"b": cfg["brands"], "r": cfg["rules"]},
                      ensure_ascii=False, sort_keys=True)


@st.cache_data(show_spinner="Проверяем посты…")
def cached_base_checks(file_bytes: bytes, cfg_sig: str) -> dict[str, list[Issue]]:
    """Проверки реестра и текстов (не зависят от месяца), кешируются."""
    wb = cached_load(file_bytes)
    cfg = config_mod.load_all()
    registry = registry_checks.run_registry_checks(wb.registry, cfg["brands"],
                                                   cfg["rules"])
    text = text_checks.run_text_checks(wb.posts, cfg["brands"], cfg["rules"])
    return {"registry": registry, "text": text}


@dataclass
class AppData:
    wb: loader_mod.LoadedWorkbook
    cfg: dict
    posts: list[PostRecord]
    registry_by_row: dict[int, RegistryRow]
    issues: list[Issue]                              # без скрытых
    issues_by_post: dict[tuple, list[Issue]]         # (sheet,row) -> issues
    post_status: dict[tuple, str]                    # (sheet,row) -> статус
    executors: list[str]


def get_config() -> dict:
    return config_mod.load_all()


def build_app_data(file_bytes: bytes) -> AppData:
    """Собрать всё необходимое для интерфейса. Тяжёлые проверки кешируются."""
    cfg = get_config()
    wb = cached_load(file_bytes)
    base = cached_base_checks(file_bytes, _config_signature(cfg))

    ignored = set(config_mod.load_ignored().keys())

    def visible(iss: Issue) -> bool:
        return config_mod.ignore_key(iss.sheet, iss.row, iss.code) not in ignored

    issues = [i for i in (base["registry"] + base["text"]) if visible(i)]

    posts: list[PostRecord] = []
    for brand_posts in wb.posts.values():
        posts.extend(brand_posts)

    registry_by_row = {rr.row: rr for rr in wb.registry}

    # статус поста берём из реестра по совпадению ссылок
    link_status: dict[str, str] = {}
    for rr in wb.registry:
        for norm in rr.links_norm:
            if norm:
                # «Выложено» приоритетнее «Готово»
                if link_status.get(norm) != "Выложено":
                    link_status[norm] = rr.status
    post_status: dict[tuple, str] = {}
    for p in posts:
        status = ""
        for s in p.socials:
            norm = N.normalize_link(s.get("link", ""))
            if norm in link_status:
                if link_status[norm] == "Выложено":
                    status = "Выложено"
                    break
                status = status or link_status[norm]
        post_status[(p.sheet, p.row)] = status

    issues_by_post: dict[tuple, list[Issue]] = {}
    for i in issues:
        issues_by_post.setdefault((i.sheet, i.row), []).append(i)

    executors = sorted({p.executor for p in posts if p.executor
                        and p.executor != "-"})

    return AppData(wb=wb, cfg=cfg, posts=posts, registry_by_row=registry_by_row,
                   issues=issues, issues_by_post=issues_by_post,
                   post_status=post_status, executors=executors)


def issue_date(iss: Issue, data: AppData) -> Optional[dt.date]:
    if iss.sheet == loader_mod.REGISTRY_SHEET:
        rr = data.registry_by_row.get(iss.row)
        if rr:
            return rr.pub_date or rr.write_date
        return None
    post = _post_by_key(data, (iss.sheet, iss.row))
    return post.date if post else None


def _post_by_key(data: AppData, key: tuple) -> Optional[PostRecord]:
    for p in data.posts:
        if (p.sheet, p.row) == key:
            return p
    return None


# ---------------------------------------------------------------------------
# Выбор месяца (общий для всех экранов)
# ---------------------------------------------------------------------------
def available_months(data: AppData) -> list[tuple[int, int, int]]:
    """Список (год, месяц, число постов), от новых к старым."""
    counts: dict[tuple[int, int], int] = {}
    for p in data.posts:
        if p.date:
            key = (p.date.year, p.date.month)
            counts[key] = counts.get(key, 0) + 1
    ordered = sorted(counts.keys(), reverse=True)
    return [(y, m, counts[(y, m)]) for (y, m) in ordered]


def ensure_period(data: AppData) -> None:
    """Задать месяц по умолчанию (текущий по МСК или ближайший с постами)."""
    if "period" in st.session_state:
        return
    months = [(y, m) for (y, m, _) in available_months(data)]
    today = moscow_today()
    cur = (today.year, today.month)
    if not months:
        st.session_state["period"] = cur
        st.session_state["period_note"] = ""
        return
    if cur in months:
        st.session_state["period"] = cur
        st.session_state["period_note"] = ""
    else:
        nearest = min(months, key=lambda ym: abs((ym[0] - cur[0]) * 12
                                                 + (ym[1] - cur[1])))
        st.session_state["period"] = nearest
        st.session_state["period_note"] = (
            f"За {fmt_month_lower(*cur)} постов в файле пока нет, "
            f"показан {fmt_month_lower(*nearest)}.")


def current_period() -> Any:
    """Вернуть (year, month) или None (все месяцы)."""
    return st.session_state.get("period")


def _period_options(data: AppData) -> list[Any]:
    opts: list[Any] = [(y, m) for (y, m, _) in available_months(data)]
    opts.append(None)  # «Все месяцы»
    return opts


def month_selector(data: AppData, key_prefix: str = "posts") -> None:
    """Строка выбора месяца: ← [список] →. Обновляет session_state['period']."""
    ensure_period(data)
    months_info = {(y, m): c for (y, m, c) in available_months(data)}
    options = _period_options(data)
    current = current_period()
    if current not in options:
        current = options[0] if options else None
        st.session_state["period"] = current

    note = st.session_state.get("period_note")
    if note:
        st.info(note)

    idx = options.index(current)
    col_prev, col_sel, col_next = st.columns([1, 6, 1])

    with col_prev:
        # предыдущий месяц = более старый = следующий индекс (список по убыванию)
        disabled = current is None or idx >= len(options) - 2
        if st.button("←", key=f"{key_prefix}_prev", disabled=disabled,
                     use_container_width=True, help="Предыдущий месяц"):
            st.session_state["period"] = options[idx + 1]
            st.session_state["period_note"] = ""
            st.rerun()

    with col_sel:
        def label(opt):
            if opt is None:
                return "Все месяцы"
            y, m = opt
            return f"{fmt_month(y, m)} ({months_info.get((y, m), 0)} постов)"
        chosen = st.selectbox("Месяц", options, index=idx, format_func=label,
                              key=f"{key_prefix}_month_sel",
                              label_visibility="collapsed")
        if chosen != current:
            st.session_state["period"] = chosen
            st.session_state["period_note"] = ""
            st.rerun()

    with col_next:
        # следующий месяц = более новый = предыдущий индекс
        disabled = current is None or idx == 0
        if st.button("→", key=f"{key_prefix}_next", disabled=disabled,
                     use_container_width=True, help="Следующий месяц"):
            st.session_state["period"] = options[idx - 1]
            st.session_state["period_note"] = ""
            st.rerun()


def period_matches(d: Optional[dt.date], period: Any) -> bool:
    if period is None:
        return True
    if not d:
        return False
    return (d.year, d.month) == period


def period_title(period: Any) -> str:
    if period is None:
        return "все месяцы"
    return fmt_month_lower(*period)


# ---------------------------------------------------------------------------
# Фильтры (общие)
# ---------------------------------------------------------------------------
FILTER_DEFAULTS = {
    "f_brands": [],
    "f_executor": "Все",
    "f_levels": [Level.ERROR, Level.WARNING],
    "f_status": [],
    "f_search": "",
    "f_only_issues": True,
}


def _reset_filters() -> None:
    for k, v in FILTER_DEFAULTS.items():
        st.session_state[k] = list(v) if isinstance(v, list) else v


def filters_bar(data: AppData, brand_only: bool = False) -> dict:
    """Горизонтальные фильтры. brand_only=True — только бренд (для публикаций)."""
    for k, v in FILTER_DEFAULTS.items():
        st.session_state.setdefault(k, list(v) if isinstance(v, list) else v)

    brand_codes = list(data.cfg["brands"].keys())

    if brand_only:
        brands = st.pills("Бренд", brand_codes, selection_mode="multi",
                          default=st.session_state["f_brands"], key="f_brands")
        return {"brands": brands or brand_codes}

    row1 = st.columns([2, 2, 2])
    with row1[0]:
        brands = st.pills("Бренд", brand_codes, selection_mode="multi",
                          key="f_brands")
    with row1[1]:
        execs = ["Все"] + data.executors
        if st.session_state["f_executor"] not in execs:
            st.session_state["f_executor"] = "Все"
        executor = st.selectbox("Исполнитель", execs, key="f_executor")
    with row1[2]:
        level_opts = list(LEVEL_LABELS.values())
        chosen_labels = st.pills("Уровень замечаний", level_opts,
                                 selection_mode="multi",
                                 default=[LEVEL_LABELS[l] for l in
                                          st.session_state["f_levels"]],
                                 key="f_levels_labels")
        rev = {v: k for k, v in LEVEL_LABELS.items()}
        levels = [rev[l] for l in chosen_labels]

    row2 = st.columns([2, 3, 2, 1.4])
    with row2[0]:
        status = st.pills("Статус", ["Готово", "Выложено"],
                          selection_mode="multi", key="f_status")
    with row2[1]:
        search = st.text_input("Поиск", key="f_search",
                               placeholder="Поиск по тексту поста",
                               label_visibility="visible")
    with row2[2]:
        only_issues = st.toggle("Только с замечаниями", key="f_only_issues")
    with row2[3]:
        st.write("")
        st.button("Сбросить фильтры", on_click=_reset_filters,
                  use_container_width=True)

    result = {
        "brands": brands or brand_codes,
        "executor": executor,
        "levels": levels,
        "status": status,
        "search": search.strip().lower() if search else "",
        "only_issues": only_issues,
    }
    st.session_state["active_filters"] = result
    return result


def default_filters(data: "AppData") -> dict:
    return {
        "brands": list(data.cfg["brands"].keys()),
        "executor": "Все",
        "levels": [Level.ERROR, Level.WARNING],
        "status": [],
        "search": "",
        "only_issues": True,
    }


def current_filters(data: "AppData") -> dict:
    """Активные фильтры (заданные на экране «Проверка постов») или значения
    по умолчанию — для кнопки скачивания на любой странице."""
    return st.session_state.get("active_filters") or default_filters(data)


def post_issues_filtered(data: AppData, post: PostRecord,
                         levels: list[Level]) -> list[Issue]:
    issues = data.issues_by_post.get((post.sheet, post.row), [])
    if levels:
        return [i for i in issues if i.level in levels]
    return [i for i in issues if i.level != Level.TECH]


def apply_filters(data: AppData, filters: dict, period: Any
                  ) -> list[tuple[PostRecord, list[Issue]]]:
    result = []
    for p in data.posts:
        if not period_matches(p.date, period):
            continue
        if filters["brands"] and p.brand not in filters["brands"]:
            continue
        if filters.get("executor", "Все") != "Все" and \
           p.executor != filters["executor"]:
            continue
        if filters.get("status"):
            if data.post_status.get((p.sheet, p.row), "") not in filters["status"]:
                continue
        if filters.get("search"):
            if filters["search"] not in (p.text or "").lower():
                continue
        p_issues = post_issues_filtered(data, p, filters.get("levels", []))
        if filters.get("only_issues") and not p_issues:
            continue
        result.append((p, p_issues))
    return result


# ---------------------------------------------------------------------------
# Орфография (кеш по тексту)
# ---------------------------------------------------------------------------
@st.cache_data(show_spinner=False)
def cached_spell(text: str, whitelist_key: tuple, timeout: int
                 ) -> tuple[str, list[dict]]:
    return speller.spell_text(text, set(whitelist_key), timeout)


def spell_for_post(post: PostRecord, cfg: dict) -> tuple[str, list[dict]]:
    wl = tuple(sorted(cfg["whitelist"]))
    timeout = cfg["rules"].get("online", {}).get("timeout_seconds", 10)
    return cached_spell(post.text or "", wl, timeout)


# ---------------------------------------------------------------------------
# Боковая панель: файл + экспорт
# ---------------------------------------------------------------------------
def _load_file_bytes(file_bytes: bytes, name: str) -> None:
    st.session_state["file_bytes"] = file_bytes
    st.session_state["file_name"] = name
    st.session_state["file_time"] = moscow_today().strftime("%d.%m.%Y")
    # сбросить период — пересчитается под новый файл
    st.session_state.pop("period", None)
    st.session_state.pop("period_note", None)


def sidebar_file_block() -> Optional[bytes]:
    """Блок работы с файлом в боковой панели. Возвращает file_bytes или None."""
    st.sidebar.title("Проверка постов")
    data = st.session_state.get("file_bytes")

    with st.sidebar:
        if not data:
            up = st.file_uploader("Файл реестра (.xlsx)", type=["xlsx"],
                                  key="uploader_main")
            if up is not None:
                _load_file_bytes(up.getvalue(), up.name)
                st.rerun()
            _google_block()
        else:
            st.caption(f"Загружено: **{st.session_state.get('file_name')}**")
            st.caption(f"Дата загрузки: {st.session_state.get('file_time', '')}")
            if st.button("Загрузить другой", key="reload_btn"):
                for k in ("file_bytes", "file_name", "file_time"):
                    st.session_state.pop(k, None)
                st.rerun()
    return st.session_state.get("file_bytes")


def _google_block() -> None:
    """Загрузка из Google-таблицы (если задан сервисный аккаунт)."""
    from checker import gsheets
    try:
        sa = st.secrets.get("gcp_service_account_json") or \
             st.secrets.get("gcp_service_account")  # type: ignore
    except Exception:  # noqa: BLE001
        sa = None
    if not sa:
        return
    with st.expander("Из Google-таблицы"):
        url = st.text_input("Ссылка на Google-таблицу",
                            key="gsheet_url_side",
                            placeholder="https://docs.google.com/spreadsheets/d/…")
        if st.button("Загрузить из Google", key="gload_btn"):
            if not url.strip():
                st.error("Вставьте ссылку.")
            else:
                try:
                    with st.spinner("Скачиваем таблицу…"):
                        b = gsheets.download_as_xlsx(url, sa)
                    _load_file_bytes(b, "Google-таблица")
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(f"Не удалось получить таблицу: {e}")


def sidebar_download(data: AppData, filtered: list[tuple[PostRecord, list[Issue]]],
                     period: Any) -> None:
    """Кнопка скачивания отчёта за выбранный месяц с учётом фильтров."""
    # собрать замечания: по отфильтрованным постам + реестр за месяц
    issues: list[Issue] = []
    for _, p_issues in filtered:
        issues.extend(p_issues)
    for i in data.issues:
        if i.sheet == loader_mod.REGISTRY_SHEET:
            if period_matches(issue_date(i, data), period):
                issues.append(i)

    total_posts = len(filtered)
    summary = summarize(issues, total_posts)
    try:
        xlsx = report_mod.build_xlsx(issues, summary)
    except Exception:  # noqa: BLE001
        return

    if period is None:
        fname = "Проверка_постов_все.xlsx"
        label = "📥 Скачать отчёт за все месяцы"
    else:
        y, m = period
        fname = f"Проверка_постов_{y}-{m:02d}.xlsx"
        label = f"📥 Скачать отчёт за {fmt_month_lower(y, m)}"

    st.sidebar.download_button(
        label, data=xlsx, file_name=fname,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True, key="dl_report")


# ---------------------------------------------------------------------------
# Пустые состояния
# ---------------------------------------------------------------------------
def empty_no_file() -> None:
    st.title("Проверка постов в реестре")
    st.markdown(
        "### Загрузите файл реестра в панели слева ⬅️\n\n"
        "Сервис читает реестр «РРП. Реестр постов/отгрузок» и находит ошибки: "
        "пустые поля и неверные даты, дубли и чужие ссылки, отсутствие контактов "
        "и хэштегов, остатки шаблонов и промтов, опечатки и типографику, "
        "нехватку постов к праздникам.\n\n"
        "Загрузить можно файлом `.xlsx` или прямо из Google-таблицы."
    )
