"""Нормализация данных: даты, ссылки, телефоны, названия соцсетей и типов постов.

Все функции чистые (без побочных эффектов) и не зависят от Streamlit.
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

# --- символы дефисов/тире и пробелов (для телефонов) ---
DASHES = "-‐‑‒–—−"  # - ‐ ‑ ‒ – — −
SPACES = "     "              # обычный, неразрывный, узкий и т.п.

_DASH_RE = re.compile("[" + re.escape(DASHES) + "]")
_SPACE_RE = re.compile("[" + re.escape(SPACES) + "]")


# ---------------------------------------------------------------------------
# ДАТЫ
# ---------------------------------------------------------------------------
_EXCEL_EPOCH = dt.date(1899, 12, 30)  # серийные даты Excel считаются отсюда

_DATE_TEXT_RE = re.compile(r"^\s*(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2,4})\s*$")


def parse_date(value: Any) -> tuple[Optional[dt.date], Optional[str]]:
    """Привести значение к date.

    Возвращает (дата, ошибка). Если распознать не удалось — (None, текст_ошибки).
    Пустое значение — (None, None): это не ошибка распознавания, а просто пусто.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, None

    if isinstance(value, dt.datetime):
        return value.date(), None
    if isinstance(value, dt.date):
        return value, None

    # число-серийник Excel
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            n = int(round(float(value)))
            if 1 <= n <= 60000:
                return _EXCEL_EPOCH + dt.timedelta(days=n), None
        except (ValueError, OverflowError):
            return None, f"не удалось распознать число как дату: {value!r}"

    s = str(value).strip()
    # текст ДД.ММ.ГГГГ (или через - /)
    m = _DATE_TEXT_RE.match(s)
    if m:
        d, mth, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return dt.date(y, mth, d), None
        except ValueError:
            return None, f"некорректная дата: {s!r}"

    # число, записанное как текст
    if re.fullmatch(r"\d{4,6}", s):
        n = int(s)
        if 1 <= n <= 60000:
            return _EXCEL_EPOCH + dt.timedelta(days=n), None

    return None, f"не удалось распознать дату: {s!r}"


# ---------------------------------------------------------------------------
# ССЫЛКИ
# ---------------------------------------------------------------------------
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

# хвосты-параметры, которые не меняют смысл ссылки
_DROP_QUERY_KEYS = {"utm_campaign", "utm_source", "utm_medium", "utm_content",
                    "utm_term", "from", "share_to", "w", "reply", "embed"}

_DOMAIN_ALIASES = {
    "vk.ru": "vk.com",
    "m.vk.com": "vk.com",
    "www.vk.com": "vk.com",
    "m.ok.ru": "ok.ru",
    "www.ok.ru": "ok.ru",
    "telegram.me": "t.me",
    "www.t.me": "t.me",
}


def extract_links(cell: Any) -> list[str]:
    """Достать все ссылки из ячейки (через пробелы, переносы строк, кавычки)."""
    if cell is None:
        return []
    text = str(cell)
    return [m.group(0).rstrip(".,;)") for m in _URL_RE.finditer(text)]


def normalize_link(url: str) -> str:
    """Привести ссылку к каноническому виду для сравнения и поиска дублей."""
    if not url:
        return ""
    u = url.strip().strip('"\'')
    u = re.sub(r"^https?://", "", u, flags=re.IGNORECASE)
    # отделить домен и путь от query/fragment
    u = u.split("#", 1)[0]
    if "?" in u:
        path, query = u.split("?", 1)
    else:
        path, query = u, ""
    if "/" in path:
        domain, rest = path.split("/", 1)
    else:
        domain, rest = path, ""
    domain = domain.lower()
    domain = _DOMAIN_ALIASES.get(domain, domain)
    # оставить только значимые query-параметры
    kept = []
    if query:
        for part in query.split("&"):
            key = part.split("=", 1)[0].lower()
            if key and key not in _DROP_QUERY_KEYS:
                kept.append(part)
    rest = rest.rstrip("/")
    norm = domain + ("/" + rest if rest else "")
    if kept:
        norm += "?" + "&".join(sorted(kept))
    return norm


def link_domain(url: str) -> str:
    n = normalize_link(url)
    return n.split("/", 1)[0] if n else ""


def is_private_tg_link(url: str) -> bool:
    """Ссылка вида t.me/c/2203619795/... — закрытый рабочий чат."""
    n = normalize_link(url)
    return bool(re.match(r"t\.me/c/\d+", n))


def tg_channel_from_link(url: str) -> Optional[str]:
    """Достать имя публичного Telegram-канала из ссылки (t.me/name/123)."""
    n = normalize_link(url)
    m = re.match(r"t\.me/([A-Za-z0-9_]+)(?:/|$)", n)
    if m and m.group(1) != "c":
        return m.group(1).lower()
    return None


def vk_group_id_from_link(url: str) -> Optional[str]:
    """Достать id группы VK из ссылки (vk.com/wall-217668235_819 или /public...)."""
    n = normalize_link(url)
    if not n.startswith("vk.com"):
        return None
    m = re.search(r"wall(-?\d+)_", n)
    if m:
        return m.group(1)
    m = re.search(r"(?:club|public)(\d+)", n)
    if m:
        return "-" + m.group(1)
    return None


def ok_group_id_from_link(url: str) -> Optional[str]:
    """Достать id группы OK (ok.ru/group/70000004574376/...)."""
    n = normalize_link(url)
    if not n.startswith("ok.ru"):
        return None
    m = re.search(r"group/(\d+)", n)
    if m:
        return m.group(1)
    return None


def max_channel_id_from_link(url: str) -> Optional[str]:
    n = normalize_link(url)
    m = re.search(r"max\.ru/.*?(-?\d{6,})", n)
    if m:
        return m.group(1)
    return None


# ---------------------------------------------------------------------------
# ТЕЛЕФОНЫ
# ---------------------------------------------------------------------------
def normalize_phone(text: str) -> str:
    """Оставить только цифры (для строгого сравнения по номеру)."""
    if not text:
        return ""
    return re.sub(r"\D", "", str(text))


def normalize_phone_soft(text: str) -> str:
    """Нормализовать дефисы, тире и пробелы, но сохранить структуру записи."""
    if not text:
        return ""
    s = _DASH_RE.sub("-", str(text))
    s = _SPACE_RE.sub(" ", s)
    return s.strip()


def phones_equal(a: str, b: str) -> tuple[bool, bool]:
    """Сравнить телефоны. Возвращает (равны_по_цифрам, записаны_ли_одинаково).

    «Записаны одинаково» — совпадают посимвольно после схлопывания разных
    видов пробелов, но БЕЗ унификации дефисов/тире. Так мы отличаем случай,
    когда номер совпадает только благодаря нормализации дефисов.
    """
    if not a or not b:
        return False, False
    same_digits = normalize_phone(a) == normalize_phone(b)
    a_sp = _SPACE_RE.sub(" ", str(a)).strip()
    b_sp = _SPACE_RE.sub(" ", str(b)).strip()
    same_literal = a_sp == b_sp
    return same_digits, same_literal


# ---------------------------------------------------------------------------
# СОЦСЕТИ и ТИПЫ ПОСТОВ (нормализация по словарю из конфига)
# ---------------------------------------------------------------------------
def _canonicalize(value: str, mapping: dict[str, list[str]]) -> tuple[str, bool]:
    """Вернуть (каноническое_значение, совпадало_ли_дословно)."""
    if not value:
        return "", True
    raw = str(value).strip()
    stripped = re.sub(r"\s+", " ", raw)
    for canon, variants in mapping.items():
        if stripped == canon:
            return canon, True
        for v in variants:
            if stripped.lower() == str(v).strip().lower():
                return canon, False
        if stripped.lower() == canon.lower():
            return canon, False
    return stripped, True  # неизвестное значение оставляем как есть


def canonical_social(value: str, mapping: dict[str, list[str]]) -> tuple[str, bool]:
    return _canonicalize(value, mapping)


def canonical_post_type(value: str, mapping: dict[str, list[str]]) -> tuple[str, bool]:
    if value is None:
        return "", True
    # убрать переносы строк и лишние пробелы
    cleaned = re.sub(r"\s+", " ", str(value)).strip()
    canon, literal = _canonicalize(cleaned, mapping)
    # literal=True если совпало с эталоном И исходное значение было «чистым»
    literal_full = literal and cleaned == str(value).strip()
    return canon, literal_full
