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


def fmt_date_compact(d: Optional[dt.date]) -> str:
    """Дата без года для списка постов: «02.09, ср»."""
    if not d:
        return ""
    return f"{d:%d.%m}, {WEEKDAYS_SHORT[d.weekday()]}"


def fmt_date_full(d: Optional[dt.date]) -> str:
    if not d:
        return "Дата не указана"
    return f"{d.day} {MONTHS_GEN[d.month]} {d.year}, {WEEKDAYS_FULL[d.weekday()]}"


def norm_type(value: str, rules: dict) -> str:
    """Нормализовать тип поста для показа (Информативый → Информационный)."""
    canon, _ = N.canonical_post_type(value, rules.get("post_type_canonical", {}))
    return canon or (value or "")


# ---------------------------------------------------------------------------
# Склонение по числу (общая функция для всего интерфейса)
# ---------------------------------------------------------------------------
def plural(n: int, one: str, few: str, many: str) -> str:
    """Выбрать форму слова по числу: 1 пост, 2 поста, 5 постов."""
    n = abs(int(n))
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def plural_posts(n: int) -> str:
    return f"{n} {plural(n, 'пост', 'поста', 'постов')}"


def plural_links(n: int) -> str:
    return f"{n} {plural(n, 'ссылка', 'ссылки', 'ссылок')}"


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
    # переопределение уровней проверок из настроек
    overrides = cfg["rules"].get("check_levels", {})
    if overrides:
        for i in registry + text:
            if i.code in overrides:
                try:
                    i.level = Level(overrides[i.code])
                except ValueError:
                    pass
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


# ---------------------------------------------------------------------------
# Хранение настроек в отдельной Google-таблице
# ---------------------------------------------------------------------------
def settings_url() -> Optional[str]:
    try:
        return st.secrets.get("settings_sheet_url")  # type: ignore
    except Exception:  # noqa: BLE001
        return None


def settings_status() -> tuple[bool, str]:
    """(сохраняются_ли_постоянно, текст статуса)."""
    if settings_url() and get_service_account():
        return True, ("✅ Настройки сохраняются в Google-таблицу «Настройки "
                      "проверки постов»")
    return False, ("⚠️ Настройки сохраняются только до перезапуска сервиса. "
                   "Подключите таблицу настроек или скачивайте резервную копию")


def pull_settings() -> None:
    """Один раз за сессию подтянуть настройки из таблицы в config-файлы."""
    if st.session_state.get("_settings_pulled"):
        return
    st.session_state["_settings_pulled"] = True
    url, sa = settings_url(), get_service_account()
    if not url or not sa:
        return
    try:
        from checker import settings_store
        bundle = settings_store.read_bundle(url, sa)
    except Exception:  # noqa: BLE001
        return
    if not bundle:
        return
    if "brands" in bundle:
        config_mod.save_brands(bundle["brands"])
    if "rules" in bundle:
        config_mod.save_rules(bundle["rules"])
    if "whitelist" in bundle:
        config_mod.save_whitelist(bundle["whitelist"])
    if "ignored" in bundle:
        config_mod.save_ignored(bundle["ignored"])
    if "manual" in bundle:
        config_mod.save_manual(bundle["manual"])
    if "source" in bundle:
        config_mod.save_source(bundle["source"])
    cached_base_checks.clear()
    cached_spell.clear()
    clear_source_cache()


def persist_all() -> bool:
    """Сбросить кеши проверок и, если подключена таблица настроек, записать в неё."""
    cached_base_checks.clear()
    cached_spell.clear()
    url, sa = settings_url(), get_service_account()
    if not url or not sa:
        return False
    try:
        from checker import settings_store
        settings_store.write_bundle(url, sa, {
            "brands": config_mod.load_brands(),
            "rules": config_mod.load_rules(),
            "whitelist": sorted(config_mod.load_whitelist()),
            "ignored": config_mod.load_ignored(),
            "manual": config_mod.load_manual(),
            "source": config_mod.load_source(),
        })
        return True
    except Exception:  # noqa: BLE001
        return False


@st.cache_data(show_spinner=False)
def _cached_text_links(sid: str, titles: tuple, _sa) -> dict:
    """Анкор-гиперссылки по листам брендов (кешируется до «Обновить данные»)."""
    from checker import gsheets
    out: dict[str, dict] = {}
    for t in titles:
        try:
            out[t] = gsheets.fetch_text_links(sid, t, _sa)
        except Exception:  # noqa: BLE001
            out[t] = {}
    return out


def _attach_text_links(posts: list[PostRecord]) -> None:
    """Подмешать анкор-ссылки из Google-таблицы в posts (для проверки сайта)."""
    src = st.session_state.get("sheet_source") or {}
    if src.get("is_excel") or not src.get("id"):
        return  # Excel-ссылки уже прочитаны загрузчиком
    sa = get_service_account()
    if not sa:
        return
    titles = tuple(sorted({p.sheet for p in posts}))
    if not titles:
        return
    try:
        links_by_sheet = _cached_text_links(src["id"], titles, sa)
    except Exception:  # noqa: BLE001
        return
    for p in posts:
        for u in (links_by_sheet.get(p.sheet, {}) or {}).get(p.row, []) or []:
            if u not in p.text_links:
                p.text_links.append(u)


def _site_resolved_keys(posts: list[PostRecord], cfg: dict) -> set[tuple]:
    """Посты, где сайт фактически есть (домен в тексте или ссылка-анкор)."""
    from checker import text_checks as T
    rules, brands = cfg["rules"], cfg["brands"]
    resolved = set()
    for p in posts:
        site = str(brands.get(p.brand, {}).get("site", "")).lower()
        if site and T._site_status(p, site, rules) == "ok":
            resolved.add((p.sheet, p.row))
    return resolved


def build_app_data(file_bytes: bytes) -> AppData:
    """Собрать всё необходимое для интерфейса. Тяжёлые проверки кешируются."""
    cfg = get_config()
    wb = cached_load(file_bytes)
    base = cached_base_checks(file_bytes, _config_signature(cfg))

    ignored = set(config_mod.load_ignored().keys())
    disabled = {code for code, b in cfg["brands"].items()
                if not b.get("enabled", True)}

    posts: list[PostRecord] = []
    for code, brand_posts in wb.posts.items():
        if code in disabled:
            continue
        posts.extend(brand_posts)

    # анкор-ссылки из Google-таблицы (кеш) — чтобы сайт-анкор не считался ошибкой
    _attach_text_links(posts)
    site_resolved = _site_resolved_keys(posts, cfg)

    registry_by_row = {rr.row: rr for rr in wb.registry}
    post_text_by_key = {(p.sheet, p.row): p.text for p in posts}

    def issue_cell_text(iss: Issue) -> str:
        if iss.sheet == loader_mod.REGISTRY_SHEET:
            rr = registry_by_row.get(iss.row)
            return rr.links_raw if rr else ""
        return post_text_by_key.get((iss.sheet, iss.row), "")

    def visible(iss: Issue) -> bool:
        chash = config_mod.content_hash(issue_cell_text(iss))
        return config_mod.ignore_key(iss.sheet, iss.code, chash) not in ignored

    # анкор-ссылка снимает «нет сайта», если сайт фактически есть в ячейке
    site_codes = {"text_no_site", "text_site_anchor_no_link"}
    issues = [i for i in (base["registry"] + base["text"])
              if i.brand not in disabled and visible(i)
              and not (i.code in site_codes and (i.sheet, i.row) in site_resolved)]

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


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def _year_options(data: AppData) -> list[int]:
    years = {p.date.year for p in data.posts if p.date}
    today = moscow_today()
    years.update({today.year, today.year + 1})
    return sorted(years)


def period_selector(data: AppData, key_prefix: str = "period") -> None:
    """Единый выбор месяца и года (общий для всех экранов).

    Раскладка: [←] [Месяц ▾] [Год ▾] [→] и пустая колонка справа, чтобы
    элементы не растягивались. Выбор сохраняется в session_state['period']
    как (год, месяц) и общий для всех страниц.
    """
    ensure_period(data)
    period = current_period()
    today = moscow_today()
    if isinstance(period, tuple):
        year, month = period
    else:
        year, month = today.year, today.month

    note = st.session_state.get("period_note")
    if note:
        st.info(note)

    years = _year_options(data)
    if year not in years:
        years = sorted(set(years) | {year})
    month_names = [MONTHS_NOM[i] for i in range(1, 13)]

    # Ключи виджетов кодируют текущий период: при любой смене периода (стрелки,
    # другой экран) создаётся новый виджет с правильным index, минуя «залипание»
    # состояния Streamlit.
    cols = st.columns([1, 4, 2, 1, 8], vertical_alignment="bottom")
    prev_clicked = cols[0].button("←", key=f"{key_prefix}_prev",
                                  help="Предыдущий месяц")
    sel_month = cols[1].selectbox("Месяц", month_names, index=month - 1,
                                  key=f"{key_prefix}_month_{year}_{month}")
    sel_year = cols[2].selectbox("Год", years, index=years.index(year),
                                 key=f"{key_prefix}_year_{year}_{month}")
    next_clicked = cols[3].button("→", key=f"{key_prefix}_next",
                                  help="Следующий месяц")

    if prev_clicked:
        new_year, new_month = _shift_month(year, month, -1)
    elif next_clicked:
        new_year, new_month = _shift_month(year, month, +1)
    else:
        new_month = month_names.index(sel_month) + 1
        new_year = int(sel_year)

    if (new_year, new_month) != (year, month):
        st.session_state["period"] = (new_year, new_month)
        st.session_state["period_note"] = ""
        st.rerun()


def posts_in_period(data: AppData, period: Any) -> list[PostRecord]:
    """Все посты с датой за выбранный месяц (без учёта фильтров)."""
    return [p for p in data.posts if period_matches(p.date, period)]


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
# Источник данных: Google-таблица (авто) + Excel (запасной)
# ---------------------------------------------------------------------------
def get_service_account():
    """Ключ сервисного аккаунта из секретов (dict или JSON-строка)."""
    try:
        return (st.secrets.get("gcp_service_account_json")     # type: ignore
                or st.secrets.get("gcp_service_account"))      # type: ignore
    except Exception:  # noqa: BLE001
        return None


def _now_msk_hhmm() -> str:
    return dt.datetime.now(ZoneInfo("Europe/Moscow")).strftime("%H:%M")


def _reset_period() -> None:
    st.session_state.pop("period", None)
    st.session_state.pop("period_note", None)


@st.cache_data(show_spinner="Загружаем таблицу из Google…")
def _load_table(url: str, method: str, gids_extra: tuple, _sa) -> dict:
    """Скачать таблицу и метаданные. Кешируется, пока не нажали «Обновить»."""
    from checker import gsheets
    if method == "public":
        data = gsheets.download_public(url)
        meta = {"title": "Google-таблица", "sheets": []}
    else:
        data = gsheets.download_service_account(url, _sa)
        try:
            meta = gsheets.get_metadata(url, _sa)
        except Exception:  # noqa: BLE001
            meta = {"title": "Google-таблица", "sheets": []}
    gids = {s["title"]: s["gid"] for s in meta.get("sheets", [])
            if s.get("gid") is not None}
    gids.update({k: v for k, v in dict(gids_extra).items() if v})
    return {
        "bytes": data,
        "title": meta.get("title") or "Google-таблица",
        "gids": gids,
        "id": gsheets.extract_sheet_id(url),
        "at": dt.datetime.now(ZoneInfo("Europe/Moscow")).strftime("%H:%M"),
    }


def clear_source_cache() -> None:
    _load_table.clear()
    _cached_text_links.clear()


def fetch_source(force: bool = False) -> Optional[str]:
    """Загрузить таблицу (из кеша или заново). Вернуть текст ошибки или None."""
    src = config_mod.load_source()
    url = (src.get("url") or "").strip()
    if not url:
        return None
    method = src.get("method", "service_account")
    sa = get_service_account()
    if method != "public" and not sa:
        return "Ключ сервисного аккаунта не добавлен в секреты."

    if force:
        clear_source_cache()

    try:
        result = _load_table(url, method,
                             tuple(sorted((src.get("gids") or {}).items())), sa)
    except Exception as e:  # noqa: BLE001
        return _friendly_source_error(e)

    if st.session_state.get("excel_bytes"):
        return None  # Excel имеет приоритет

    prev_id = (st.session_state.get("sheet_source") or {}).get("id")
    st.session_state["file_bytes"] = result["bytes"]
    st.session_state["file_name"] = result["title"]
    st.session_state["file_time"] = result["at"]
    st.session_state["sheet_source"] = {
        "id": result["id"], "gids": result["gids"], "title": result["title"],
        "is_excel": False, "method": method,
    }
    if prev_id != result["id"]:
        _reset_period()
    return None


def _friendly_source_error(e: Exception) -> str:
    from checker import gsheets
    code, message = gsheets.classify_http_error(e)
    if code == "api_disabled":
        return message
    if code == "not_found":
        return "Таблица не найдена или удалена."
    if code == "no_access":
        sa = get_service_account()
        email = gsheets.sa_email(sa) if sa else ""
        return (f"Нет доступа к таблице. Откройте доступ для адреса {email} "
                f"с правами «Читатель». Если это запрещено в Google Workspace — "
                f"используйте публичную ссылку.")
    return "Не удалось загрузить таблицу. Проверьте ссылку и доступ."


def sidebar() -> Optional[bytes]:
    """Боковая панель: название, источник, обновление, экспорт. Возвращает bytes."""
    st.sidebar.title("Проверка постов")

    # Excel-режим (запасной) имеет приоритет
    if st.session_state.get("excel_bytes"):
        st.session_state["file_bytes"] = st.session_state["excel_bytes"]
        st.session_state["file_name"] = st.session_state.get("excel_name", "Excel")
        st.session_state["sheet_source"] = {"is_excel": True}
        with st.sidebar:
            st.info(f"Сейчас проверяется Excel-файл «"
                    f"{st.session_state.get('excel_name', '')}»")
            if st.button("Вернуться к Google-таблице", key="back_to_gs"):
                for k in ("excel_bytes", "excel_name"):
                    st.session_state.pop(k, None)
                _reset_period()
                st.rerun()
        return st.session_state.get("file_bytes")

    # автозагрузка из Google-таблицы
    err = fetch_source(force=False)
    src = config_mod.load_source()

    with st.sidebar:
        if src.get("url"):
            if err:
                st.error(err)
            else:
                st.markdown(f"📗 **{st.session_state.get('file_name', '')}**")
                st.caption(f"Данные на {st.session_state.get('file_time','')} (МСК)")
                if st.button("🔄 Обновить данные", key="refresh_src",
                             help="Загрузить таблицу заново",
                             use_container_width=True):
                    e2 = fetch_source(force=True)
                    if e2:
                        st.error(e2)
                    else:
                        st.rerun()
                st.link_button("Открыть таблицу", src["url"],
                               use_container_width=True)
        else:
            st.caption("Google-таблица не подключена. Откройте «Настройки» → "
                       "«Источник данных».")

        with st.expander("Загрузить Excel вместо таблицы"):
            up = st.file_uploader("Файл Excel (.xlsx)", type=["xlsx"],
                                  key="excel_uploader",
                                  help="Запасной вариант, если таблица недоступна")
            if up is not None:
                st.session_state["excel_bytes"] = up.getvalue()
                st.session_state["excel_name"] = up.name
                _reset_period()
                st.rerun()

    return st.session_state.get("file_bytes")


def sheet_link(row: Optional[int], sheet_name: str) -> Optional[str]:
    """Ссылка «Открыть в таблице» на строку листа, или None для Excel."""
    src = st.session_state.get("sheet_source") or {}
    if src.get("is_excel") or not src.get("id"):
        return None
    from checker import gsheets
    gid = (src.get("gids") or {}).get(sheet_name)
    return gsheets.open_in_sheet_url(src["id"], gid, row)


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
        "### Подключите Google-таблицу на странице «Настройки» ⚙️\n\n"
        "Откройте в меню слева **«Настройки» → «Источник данных»** и вставьте "
        "ссылку на таблицу «РРП. Реестр постов/отгрузок».\n\n"
        "_или загрузите Excel-файл в панели слева._\n\n"
        "Сервис находит ошибки: пустые поля и неверные даты, дубли и чужие ссылки, "
        "отсутствие контактов и хэштегов, остатки шаблонов и промтов, опечатки "
        "и типографику, нехватку постов к праздникам."
    )
