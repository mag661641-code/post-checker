"""Базовые структуры данных для замечаний и постов.

Модуль не зависит от Streamlit, чтобы его можно было использовать в тестах.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Optional


class Level(str, Enum):
    """Уровень важности замечания."""
    ERROR = "error"      # 🔴 нельзя публиковать / явная неточность
    WARNING = "warning"  # 🟡 проверить глазами
    ADVICE = "advice"    # 🔵 мелочь, улучшение
    TECH = "tech"        # ⚙️ техническая проблема самой проверки

    @property
    def emoji(self) -> str:
        return {
            Level.ERROR: "🔴",
            Level.WARNING: "🟡",
            Level.ADVICE: "🔵",
            Level.TECH: "⚙️",
        }[self]

    @property
    def title_ru(self) -> str:
        return {
            Level.ERROR: "Ошибка",
            Level.WARNING: "Предупреждение",
            Level.ADVICE: "Совет",
            Level.TECH: "Техническая проблема",
        }[self]


@dataclass
class Issue:
    """Одно замечание проверки.

    row — номер строки как в Excel (начиная с 1), чтобы пользователь легко нашёл ячейку.
    """
    sheet: str
    row: Optional[int]
    column: str
    level: Level
    code: str
    message: str          # что не так и почему это важно
    fix: str = ""         # как исправить
    brand: str = ""
    executor: str = ""
    post_type: str = ""
    status: str = ""
    link: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["level"] = self.level.value
        d["level_emoji"] = self.level.emoji
        d["level_title"] = self.level.title_ru
        return d


@dataclass
class PostRecord:
    """Пост, собранный из группы строк на листе бренда."""
    sheet: str
    row: int                       # номер первой строки группы в Excel
    brand: str
    date: Any = None
    post_type: str = ""
    text: str = ""
    executor: str = ""
    photos: list[str] = field(default_factory=list)
    stats_comments: list[str] = field(default_factory=list)
    socials: list[dict] = field(default_factory=list)  # {social, link, row}
    raw_rows: list[int] = field(default_factory=list)

    @property
    def links(self) -> list[str]:
        return [s["link"] for s in self.socials if s.get("link")]


@dataclass
class RegistryRow:
    """Строка главного реестра «Реестр постов»."""
    row: int
    write_date_raw: Any = None
    pub_date_raw: Any = None
    brand: str = ""
    executor: str = ""
    post_type: str = ""
    links_raw: str = ""
    status: str = ""
    write_date: Any = None         # normalized date or None
    pub_date: Any = None
    links: list[str] = field(default_factory=list)          # исходные ссылки
    links_norm: list[str] = field(default_factory=list)     # нормализованные
