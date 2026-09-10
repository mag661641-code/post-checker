"""Пакет проверок постов. Работает независимо от Streamlit."""
from __future__ import annotations

import datetime as dt
from collections import Counter
from typing import Any, Optional

from . import config as config_mod
from . import holidays as holidays_mod
from . import loader as loader_mod
from . import registry_checks
from . import report as report_mod
from . import text_checks
from .models import Issue, Level

__all__ = [
    "run_all_checks", "summarize", "loader_mod", "report_mod",
    "config_mod", "holidays_mod", "Issue", "Level",
]


def run_all_checks(workbook: "loader_mod.LoadedWorkbook", cfg: dict,
                   today: Optional[dt.date] = None,
                   holiday_year: Optional[int] = None,
                   holiday_month: Optional[int] = None) -> dict[str, list[Issue]]:
    """Запустить все офлайн-проверки. Возвращает словарь по разделам."""
    brands = cfg["brands"]
    rules = cfg["rules"]
    today = today or dt.date.today()

    registry_issues: list[Issue] = []
    try:
        registry_issues = registry_checks.run_registry_checks(
            workbook.registry, brands, rules)
    except Exception as e:  # noqa: BLE001
        registry_issues = [Issue("Реестр постов", None, "", Level.TECH,
                                 "tech_registry", f"Сбой блока реестра: {e}", "")]

    text_issues: list[Issue] = []
    try:
        text_issues = text_checks.run_text_checks(workbook.posts, brands, rules)
    except Exception as e:  # noqa: BLE001
        text_issues = [Issue("тексты", None, "", Level.TECH, "tech_texts",
                             f"Сбой блока текстов: {e}", "")]

    holiday_issues: list[Issue] = []
    try:
        year = holiday_year or today.year
        holiday_issues = holidays_mod.check_holidays(
            workbook.holidays_raw, workbook.posts, brands, rules, year, holiday_month)
    except Exception as e:  # noqa: BLE001
        holiday_issues = [Issue("Обязательные праздники", None, "", Level.TECH,
                                "tech_holidays", f"Сбой блока праздников: {e}", "")]

    return {
        "registry": registry_issues,
        "text": text_issues,
        "holiday": holiday_issues,
    }


def summarize(all_issues: list[Issue], total_posts: int) -> dict[str, Any]:
    counts = Counter(i.level for i in all_issues)
    return {
        "Всего постов (листы брендов)": total_posts,
        "🔴 Ошибок": counts.get(Level.ERROR, 0),
        "🟡 Предупреждений": counts.get(Level.WARNING, 0),
        "🔵 Советов": counts.get(Level.ADVICE, 0),
        "⚙️ Технических проблем": counts.get(Level.TECH, 0),
        "Всего замечаний": len(all_issues),
    }
