"""Расчёт дат праздников и сверка с постами.

Даты бывают: настоящей датой, текстом с годом основания («30 мая 2011 год» —
повторяется ежегодно) и плавающими («последнее воскресенье сентября»).
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
from typing import Any, Optional

from . import normalize as N
from .models import Issue, Level

_MONTHS = {
    "январь": 1, "января": 1, "февраль": 2, "февраля": 2, "март": 3, "марта": 3,
    "апрель": 4, "апреля": 4, "май": 5, "мая": 5, "июнь": 6, "июня": 6,
    "июль": 7, "июля": 7, "август": 8, "августа": 8, "сентябрь": 9, "сентября": 9,
    "октябрь": 10, "октября": 10, "ноябрь": 11, "ноября": 11,
    "декабрь": 12, "декабря": 12,
}

_ORDINALS = {"перв": 1, "втор": 2, "2-": 2, "трет": 3, "3-": 3,
             "четверт": 4, "4-": 4, "последн": -1}

_WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3,
    "пятниц": 4, "суббот": 5, "воскресен": 6,
}

# Корпоративные праздники: код бренда по названию
_CORP_BRAND = {
    "сму": "СМУ", "мпэ": "МПЭ", "имп": "ИМП",
    "апс": "АПС", "мпи": "МПИ",
}


def resolve_holiday_date(date_raw: Any, month_name: str, year: int) -> Optional[dt.date]:
    """Вычислить дату праздника для заданного года."""
    # 1) обычная дата
    d, _ = N.parse_date(date_raw)
    if d is not None:
        return dt.date(year, d.month, d.day)

    s = str(date_raw or "").strip().lower()
    if not s:
        # попробуем по названию месяца без числа — нельзя
        return None

    # 2) «30 мая 2011 год» — день рождения, повторяется ежегодно
    m = re.search(r"(\d{1,2})\s+([а-яё]+)", s)
    if m:
        day = int(m.group(1))
        mon = _MONTHS.get(m.group(2))
        if mon:
            try:
                return dt.date(year, mon, day)
            except ValueError:
                return None

    # 3) плавающая дата: «<порядковое> воскресенье <месяца>»
    mon = None
    for name, num in _MONTHS.items():
        if name in s:
            mon = num
            break
    if mon is None:
        mon = _MONTHS.get(str(month_name).strip().lower())
    if mon is None:
        return None

    weekday = None
    for name, wd in _WEEKDAYS.items():
        if name in s:
            weekday = wd
            break
    if weekday is None:
        return None

    ordinal = None
    for key, val in _ORDINALS.items():
        if key in s:
            ordinal = val
            break
    if ordinal is None:
        ordinal = 1
    return _nth_weekday(year, mon, weekday, ordinal)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    """n-й weekday месяца (n=-1 — последний)."""
    days_in_month = calendar.monthrange(year, month)[1]
    matches = [dt.date(year, month, d) for d in range(1, days_in_month + 1)
               if dt.date(year, month, d).weekday() == weekday]
    if n == -1:
        return matches[-1]
    return matches[n - 1]


def build_holiday_calendar(holidays_raw: list[dict], year: int) -> list[dict]:
    """Вернуть список праздников с вычисленной датой для года."""
    out = []
    for h in holidays_raw:
        date = resolve_holiday_date(h.get("date_raw"), h.get("month", ""), year)
        corp_brand = None
        low = h.get("name", "").lower()
        if "корпоратив" in h.get("type", "").lower() or "день рождения" in low:
            for key, code in _CORP_BRAND.items():
                if key in low:
                    corp_brand = code
                    break
        out.append({
            "name": h["name"], "type": h.get("type", ""),
            "date": date, "date_raw": h.get("date_raw"),
            "corp_brand": corp_brand, "row": h.get("row"),
        })
    return out


def check_holidays(holidays_raw: list[dict], posts_by_brand: dict, brands: dict,
                   rules: dict, year: int, month: Optional[int] = None) -> list[Issue]:
    """Проверить, что к каждому празднику запланирован пост у каждого бренда."""
    window = rules.get("thresholds", {}).get("holiday_window_days", 3)
    cal = build_holiday_calendar(holidays_raw, year)
    holiday_types = {"праздник", "поздравление"}
    issues: list[Issue] = []

    for h in cal:
        if h["date"] is None:
            continue
        if month and h["date"].month != month:
            continue
        target_brands = [h["corp_brand"]] if h["corp_brand"] else list(brands.keys())
        for code in target_brands:
            if code not in posts_by_brand:
                continue
            found = False
            for post in posts_by_brand[code]:
                if not post.date:
                    continue
                canon, _ = N.canonical_post_type(post.post_type,
                                                 rules.get("post_type_canonical", {}))
                if canon.lower() not in holiday_types:
                    continue
                if abs((post.date - h["date"]).days) <= window:
                    found = True
                    break
            if not found:
                issues.append(Issue(
                    "Обязательные праздники", h.get("row"), "Праздник",
                    Level.WARNING, "holiday_missing",
                    f"К празднику «{h['name']}» ({h['date']:%d.%m.%Y}) "
                    f"не запланирован пост у бренда {code}.",
                    f"Добавьте пост типа «Праздник» или «Поздравление» в пределах "
                    f"±{window} дней от даты праздника.",
                    brand=code,
                ))
    return issues
