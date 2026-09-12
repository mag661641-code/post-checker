"""Онлайн-проверка опубликованных постов (по кнопке на экране «Проверка публикаций»).

Идёт в интернет: таймаут, пауза между запросами, аккуратная обработка ошибок.
Никаких неофициальных API — только официальные методы (VK wall.getById при
наличии ключа) и проверка доступности/чтение публичного HTML.

Каждая ссылка превращается в LinkResult с честным статусом — результат
показывает ровно то, что удалось проверить, и не выдаёт «совпадает» там, где
текст на самом деле не сверялся.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup

try:
    from rapidfuzz import fuzz
except Exception:  # noqa: BLE001
    fuzz = None

from . import normalize as N
from .models import PostRecord

# Заголовок обычного браузера — некоторые площадки отдают роботам заглушку.
_BROWSER_UA = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "ru-RU,ru;q=0.9",
}

# --- статусы результата ---
STATUS_ICON = {
    "ok": "✅",        # текст/заголовок совпадает
    "diff": "⚠️",      # текст получен, но отличается
    "link": "🔗",      # страница открывается, текст не сверялся
    "missing": "❌",   # пост не найден (404, удалён, пусто)
    "blocked": "🔒",   # площадка не пустила робота (капча, вход, 403/429, таймаут)
    "chat": "⚠️",      # ссылка на чат, а не на публикацию канала
    "foreign": "⚠️",   # канал другого бренда
    "no_link": "➖",    # площадка ожидается, но ссылки в реестре нет
    "manual": "👁",     # отмечено «проверено вручную»
}
STATUS_TEXT = {
    "ok": "Текст совпадает",
    "diff": "Текст отличается",
    "link": "Открывается, текст не сверялся",
    "missing": "Пост не найден",
    "blocked": "Проверьте вручную",
    "chat": "Это ссылка на чат, а не на публикацию канала",
    "foreign": "Канал другого бренда",
    "no_link": "Нет ссылки",
    "manual": "Проверено вручную",
}

PLATFORMS = ["Telegram", "ВКонтакте", "Одноклассники", "Max", "WhatsApp", "Дзен"]


@dataclass
class LinkResult:
    platform: str
    url: str
    status: str          # ключ из STATUS_ICON (кроме no_link/manual — они уровнем UI)
    note: str = ""
    published: str = ""
    expected: str = ""
    channel: str = ""    # имя канала (для подсказки, напр. Telegram-канал)


# ---------------------------------------------------------------------------
# Определение площадки и владельца канала
# ---------------------------------------------------------------------------
def detect_platform(url: str) -> str:
    d = N.link_domain(url)
    if d in ("t.me", "telegram.me"):
        return "Telegram"
    if d == "vk.com":
        return "ВКонтакте"
    if d == "ok.ru":
        return "Одноклассники"
    if d == "max.ru":
        return "Max"
    if d in ("whatsapp.com", "wa.me", "chat.whatsapp.com"):
        return "WhatsApp"
    if d == "dzen.ru":
        return "Дзен"
    return d or "?"


def owning_brand(url: str, brands: dict) -> Optional[str]:
    """Какому бренду принадлежит канал по ссылке (по id из настроек). None — не определить."""
    if not brands:
        return None
    d = N.link_domain(url)
    if d in ("t.me", "telegram.me"):
        ch = N.tg_channel_from_link(url)
        if not ch:
            return None
        for code, b in brands.items():
            tg = b.get("telegram", {}) or {}
            names = {str(tg.get("clients", "")).lower(), str(tg.get("staff", "")).lower()}
            if ch in names:
                return code
        return None
    if d == "vk.com":
        gid = N.vk_group_id_from_link(url)
        if gid is None:
            return None
        for code, b in brands.items():
            if str(b.get("vk_group_id", "")).strip() == str(gid).strip():
                return code
        return None
    if d == "ok.ru":
        gid = N.ok_group_id_from_link(url)
        if gid is None:
            return None
        for code, b in brands.items():
            if str(b.get("ok_group_id", "")).strip() == str(gid).strip():
                return code
        return None
    if d == "max.ru":
        gid = N.max_channel_id_from_link(url)
        if gid is None:
            return None
        for code, b in brands.items():
            if str(b.get("max_channel_id", "")).strip() == str(gid).strip():
                return code
        return None
    if d == "whatsapp.com":
        cid = N.whatsapp_channel_from_link(url)
        if cid is None:
            return None
        for code, b in brands.items():
            if str(b.get("whatsapp_channel", "")).strip() == str(cid).strip():
                return code
        return None
    return None


# ---------------------------------------------------------------------------
# Вспомогательное: сеть и сравнение текста
# ---------------------------------------------------------------------------
def _get(url: str, timeout: int) -> requests.Response:
    return requests.get(url, headers=_BROWSER_UA, timeout=timeout,
                        allow_redirects=True)


def _compare_text(published: str, expected: str, threshold: int) -> tuple[bool, float]:
    if fuzz is None:
        return True, 100.0
    a = re.sub(r"\s+", " ", published or "").strip()
    b = re.sub(r"\s+", " ", expected or "").strip()
    if not a or not b:
        return True, 0.0
    score = fuzz.token_set_ratio(a, b)
    return score >= threshold, score


def _html_title(html: str) -> str:
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:  # noqa: BLE001
        return ""
    og = soup.find("meta", attrs={"property": "og:title"})
    if og and og.get("content"):
        return str(og["content"]).strip()
    if soup.title and soup.title.string:
        return str(soup.title.string).strip()
    return ""


def _looks_like_captcha(html: str) -> bool:
    low = (html or "").lower()
    markers = ("captcha", "я не робот", "вы не робот", "подтвердите, что вы не робот",
               "checking your browser", "ищем ваш браузер", "smartcaptcha")
    return any(m in low for m in markers)


# ---------------------------------------------------------------------------
# Telegram (публичные каналы, embed)
# ---------------------------------------------------------------------------
def fetch_telegram_post(url: str, timeout: int = 10) -> tuple[Optional[str], str]:
    """Вернуть (текст_поста, статус). Статус: ok|deleted|unparsed|error."""
    n = N.normalize_link(url)
    m = re.match(r"t\.me/([A-Za-z0-9_]+)/(\d+)", n)
    if not m:
        return None, "error"
    embed = f"https://t.me/{m.group(1)}/{m.group(2)}?embed=1"
    try:
        resp = requests.get(embed, headers=_BROWSER_UA, timeout=timeout)
    except Exception:  # noqa: BLE001
        return None, "error"
    if resp.status_code == 404:
        return None, "deleted"
    if resp.status_code != 200:
        return None, "error"
    soup = BeautifulSoup(resp.text, "html.parser")
    if soup.select_one(".tgme_widget_message_error"):
        return None, "deleted"
    node = soup.select_one(".tgme_widget_message_text")
    if node is None:
        if soup.select_one(".tgme_widget_message"):
            return "", "ok"
        return None, "unparsed"
    return node.get_text("\n", strip=True), "ok"


def _check_telegram(post: PostRecord, url: str, rules: dict) -> LinkResult:
    ch = N.tg_channel_from_link(url) or ""
    if N.is_private_tg_link(url):
        return LinkResult("Telegram", url, "blocked",
                          note="ссылка на закрытый чат", channel=ch)
    timeout = rules.get("online", {}).get("timeout_seconds", 10)
    threshold = rules.get("thresholds", {}).get("online_similarity_threshold", 85)
    text, status = fetch_telegram_post(url, timeout)
    if status == "deleted":
        return LinkResult("Telegram", url, "missing", channel=ch)
    if status in ("error", "unparsed"):
        return LinkResult("Telegram", url, "blocked",
                          note="не удалось прочитать пост автоматически", channel=ch)
    ok, score = _compare_text(text or "", post.text, threshold)
    if ok:
        return LinkResult("Telegram", url, "ok", channel=ch,
                          published=text or "", expected=post.text)
    return LinkResult("Telegram", url, "diff", channel=ch,
                      note=f"схожесть {score:.0f}% < {threshold}%",
                      published=text or "", expected=post.text)


# ---------------------------------------------------------------------------
# ВКонтакте (официальный API wall.getById при наличии ключа)
# ---------------------------------------------------------------------------
def _vk_post_id(url: str) -> Optional[str]:
    # ловит и vk.com/wall-1_2, и vk.com/группа?w=wall-1_2
    m = re.search(r"wall(-?\d+_\d+)", str(url or ""))
    return m.group(1) if m else None


def _check_vk(post: PostRecord, url: str, rules: dict,
              vk_key: Optional[str]) -> LinkResult:
    timeout = rules.get("online", {}).get("timeout_seconds", 10)
    threshold = rules.get("thresholds", {}).get("online_similarity_threshold", 85)
    version = rules.get("online", {}).get("vk_api_version", "5.199")
    post_id = _vk_post_id(url)
    if not vk_key or not post_id:
        return _availability(url, timeout, "ВКонтакте")
    try:
        resp = requests.get("https://api.vk.com/method/wall.getById", params={
            "posts": post_id, "access_token": vk_key, "v": version,
        }, timeout=timeout)
        data = resp.json()
    except Exception:  # noqa: BLE001
        return _availability(url, timeout, "ВКонтакте")
    items = data.get("response", {})
    if isinstance(items, dict):
        items = items.get("items", [])
    if not items:
        if data.get("error"):
            return _availability(url, timeout, "ВКонтакте")
        return LinkResult("ВКонтакте", url, "missing")
    published = items[0].get("text", "")
    ok, score = _compare_text(published, post.text, threshold)
    if ok:
        return LinkResult("ВКонтакте", url, "ok",
                          published=published, expected=post.text)
    return LinkResult("ВКонтакте", url, "diff",
                      note=f"схожесть {score:.0f}% < {threshold}%",
                      published=published, expected=post.text)


# ---------------------------------------------------------------------------
# WhatsApp (каналы) — только доступность страницы
# ---------------------------------------------------------------------------
def _check_whatsapp(post: PostRecord, url: str, rules: dict) -> LinkResult:
    if N.is_whatsapp_chat_link(url):
        return LinkResult("WhatsApp", url, "chat")
    timeout = rules.get("online", {}).get("timeout_seconds", 10)
    res = _availability(url, timeout, "WhatsApp")
    if res.status == "link":
        res.note = "текст WhatsApp автоматически не проверяется"
    return res


# ---------------------------------------------------------------------------
# Дзен — сравнение заголовка статьи с первой строкой текста
# ---------------------------------------------------------------------------
def _check_dzen(post: PostRecord, url: str, rules: dict) -> LinkResult:
    timeout = rules.get("online", {}).get("timeout_seconds", 10)
    threshold = rules.get("thresholds", {}).get("online_similarity_threshold", 85)
    try:
        resp = _get(url, timeout)
    except Exception:  # noqa: BLE001
        return LinkResult("Дзен", url, "blocked", note="таймаут или ошибка сети")
    if resp.status_code == 404:
        return LinkResult("Дзен", url, "missing")
    if resp.status_code in (403, 429):
        return LinkResult("Дзен", url, "blocked", note=f"код {resp.status_code}")
    if resp.status_code != 200:
        return LinkResult("Дзен", url, "blocked", note=f"код {resp.status_code}")
    if _looks_like_captcha(resp.text):
        return LinkResult("Дзен", url, "blocked", note="проверка «я не робот»")
    title = _html_title(resp.text)
    first_line = (post.text or "").strip().split("\n", 1)[0].strip()
    if not title or not first_line:
        return LinkResult("Дзен", url, "link", note="не удалось получить заголовок")
    ok, score = _compare_text(title, first_line, threshold)
    if ok:
        return LinkResult("Дзен", url, "ok", note="заголовок совпадает",
                          published=title, expected=first_line)
    return LinkResult("Дзен", url, "diff", note=f"заголовок отличается ({score:.0f}%)",
                      published=title, expected=first_line)


# ---------------------------------------------------------------------------
# Одноклассники, Max и общий фоллбэк — проверка доступности
# ---------------------------------------------------------------------------
def _availability(url: str, timeout: int, platform: str) -> LinkResult:
    try:
        resp = _get(url, timeout)
    except Exception:  # noqa: BLE001
        return LinkResult(platform, url, "blocked", note="страница не открылась (таймаут/ошибка)")
    code = resp.status_code
    if code == 404:
        return LinkResult(platform, url, "missing")
    if code in (403, 429):
        return LinkResult(platform, url, "blocked", note=f"код {code}")
    if code == 200:
        if _looks_like_captcha(resp.text):
            return LinkResult(platform, url, "blocked", note="проверка «я не робот»")
        return LinkResult(platform, url, "link")
    return LinkResult(platform, url, "blocked", note=f"код {code}")


# ---------------------------------------------------------------------------
# Диспетчер: одна ссылка -> LinkResult
# ---------------------------------------------------------------------------
def check_link(post: PostRecord, url: str, rules: dict,
               vk_key: Optional[str] = None,
               brands: Optional[dict] = None) -> LinkResult:
    platform = detect_platform(url)
    # чужой канал определяем до похода в сеть
    if brands:
        owner = owning_brand(url, brands)
        if owner and owner != post.brand:
            return LinkResult(platform, url, "foreign",
                              note=f"похоже на канал бренда {owner}")
    timeout = rules.get("online", {}).get("timeout_seconds", 10)
    d = N.link_domain(url)
    if d in ("t.me", "telegram.me"):
        return _check_telegram(post, url, rules)
    if d == "vk.com":
        return _check_vk(post, url, rules, vk_key)
    if d == "ok.ru":
        return _availability(url, timeout, "Одноклассники")
    if d == "max.ru":
        return _availability(url, timeout, "Max")
    if d in ("whatsapp.com", "wa.me", "chat.whatsapp.com"):
        return _check_whatsapp(post, url, rules)
    if d == "dzen.ru":
        return _check_dzen(post, url, rules)
    return LinkResult(platform, url, "link", note="площадка не сверяется автоматически")
