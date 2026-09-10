"""Онлайн-проверка опубликованных постов (по кнопке).

Идёт в интернет: таймаут, пауза между запросами, аккуратная обработка ошибок.
Никаких неофициальных API — только официальные методы и проверка доступности.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Optional

import requests
from bs4 import BeautifulSoup

try:
    from rapidfuzz import fuzz
except Exception:  # noqa: BLE001
    fuzz = None

from . import normalize as N
from .models import Issue, Level, PostRecord

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PostChecker/1.0)"}


# ---------------------------------------------------------------------------
# Telegram (публичные каналы)
# ---------------------------------------------------------------------------
def fetch_telegram_post(url: str, timeout: int = 10) -> tuple[Optional[str], str]:
    """Вернуть (текст_поста, статус). Статус: ok|deleted|unparsed|error."""
    n = N.normalize_link(url)
    m = re.match(r"t\.me/([A-Za-z0-9_]+)/(\d+)", n)
    if not m:
        return None, "error"
    embed = f"https://t.me/{m.group(1)}/{m.group(2)}?embed=1"
    try:
        resp = requests.get(embed, headers=_HEADERS, timeout=timeout)
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
        # возможно, пост есть, но без текста, либо структура изменилась
        if soup.select_one(".tgme_widget_message"):
            return "", "ok"
        return None, "unparsed"
    return node.get_text("\n", strip=True), "ok"


def _compare_text(published: str, expected: str, threshold: int) -> tuple[bool, float]:
    if fuzz is None:
        return True, 100.0
    a = re.sub(r"\s+", " ", published).strip()
    b = re.sub(r"\s+", " ", expected).strip()
    if not a or not b:
        return True, 0.0
    score = fuzz.token_set_ratio(a, b)
    return score >= threshold, score


def check_telegram(post: PostRecord, url: str, rules: dict) -> list[Issue]:
    timeout = rules.get("online", {}).get("timeout_seconds", 10)
    threshold = rules.get("thresholds", {}).get("online_similarity_threshold", 85)
    text, status = fetch_telegram_post(url, timeout)
    if status == "deleted":
        return [Issue(post.sheet, post.row, "Ссылка", Level.ERROR, "online_tg_deleted",
                      f"Пост в Telegram не найден (удалён или неверная ссылка): {url}",
                      "Проверьте ссылку и наличие поста.", brand=post.brand, link=url)]
    if status in {"error", "unparsed"}:
        return [Issue(post.sheet, post.row, "Ссылка", Level.ADVICE, "online_tg_unparsed",
                      f"Не удалось прочитать пост Telegram автоматически: {url}",
                      "Проверьте пост вручную.", brand=post.brand, link=url)]
    ok, score = _compare_text(text or "", post.text, threshold)
    if not ok:
        return [Issue(post.sheet, post.row, "Пост", Level.WARNING, "online_tg_diff",
                      f"Опубликованный текст отличается от согласованного "
                      f"(схожесть {score:.0f}% < {threshold}%).",
                      "Сравните опубликованный и согласованный текст.",
                      brand=post.brand, link=url,
                      extra={"published": text, "expected": post.text})]
    return []


# ---------------------------------------------------------------------------
# ВКонтакте (официальный API wall.getById, если есть ключ)
# ---------------------------------------------------------------------------
def check_vk(post: PostRecord, url: str, rules: dict,
             service_key: Optional[str]) -> list[Issue]:
    timeout = rules.get("online", {}).get("timeout_seconds", 10)
    threshold = rules.get("thresholds", {}).get("online_similarity_threshold", 85)
    version = rules.get("online", {}).get("vk_api_version", "5.199")
    n = N.normalize_link(url)
    m = re.search(r"wall(-?\d+_\d+)", n)
    if not service_key or not m:
        return _check_availability(post, url, rules, "ВКонтакте")
    try:
        resp = requests.get("https://api.vk.com/method/wall.getById", params={
            "posts": m.group(1), "access_token": service_key, "v": version,
        }, timeout=timeout)
        data = resp.json()
    except Exception:  # noqa: BLE001
        return _check_availability(post, url, rules, "ВКонтакте")
    items = data.get("response", {})
    if isinstance(items, dict):
        items = items.get("items", [])
    if not items:
        return [Issue(post.sheet, post.row, "Ссылка", Level.ERROR, "online_vk_deleted",
                      f"Пост ВКонтакте не найден через API: {url}",
                      "Проверьте ссылку.", brand=post.brand, link=url)]
    published = items[0].get("text", "")
    ok, score = _compare_text(published, post.text, threshold)
    if not ok:
        return [Issue(post.sheet, post.row, "Пост", Level.WARNING, "online_vk_diff",
                      f"Текст ВКонтакте отличается от согласованного "
                      f"(схожесть {score:.0f}%).",
                      "Сравните тексты.", brand=post.brand, link=url,
                      extra={"published": published, "expected": post.text})]
    return []


# ---------------------------------------------------------------------------
# Одноклассники, Max, Дзен — только доступность страницы
# ---------------------------------------------------------------------------
def _check_availability(post: PostRecord, url: str, rules: dict,
                        platform: str) -> list[Issue]:
    timeout = rules.get("online", {}).get("timeout_seconds", 10)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout,
                            allow_redirects=True)
    except Exception:  # noqa: BLE001
        return [Issue(post.sheet, post.row, "Ссылка", Level.ADVICE, "online_unreachable",
                      f"{platform}: страница не открылась автоматически ({url}).",
                      "Проверьте ссылку вручную — площадка может блокировать роботов.",
                      brand=post.brand, link=url)]
    if resp.status_code == 200:
        return []
    if resp.status_code in (403, 429):
        return [Issue(post.sheet, post.row, "Ссылка", Level.ADVICE, "online_blocked",
                      f"{platform} блокирует автоматический запрос (код "
                      f"{resp.status_code}).",
                      "Проверьте ссылку вручную.", brand=post.brand, link=url)]
    return [Issue(post.sheet, post.row, "Ссылка", Level.WARNING, "online_bad_status",
                  f"{platform}: страница вернула код {resp.status_code} ({url}).",
                  "Проверьте, доступен ли пост.", brand=post.brand, link=url)]


# ---------------------------------------------------------------------------
# Диспетчер
# ---------------------------------------------------------------------------
def check_post_online(post: PostRecord, url: str, rules: dict,
                      vk_key: Optional[str] = None) -> list[Issue]:
    d = N.link_domain(url)
    if d in {"t.me", "telegram.me"}:
        if N.is_private_tg_link(url):
            return []  # закрытый чат онлайн не проверяем
        return check_telegram(post, url, rules)
    if d == "vk.com":
        return check_vk(post, url, rules, vk_key)
    if d == "ok.ru":
        return _check_availability(post, url, rules, "Одноклассники")
    if d == "max.ru":
        return _check_availability(post, url, rules, "Max")
    if d == "dzen.ru":
        return _check_availability(post, url, rules, "Дзен")
    return []


def run_online_checks(posts_by_brand: dict[str, list[PostRecord]], rules: dict,
                      vk_key: Optional[str] = None,
                      progress_cb: Optional[Callable] = None,
                      should_stop: Optional[Callable] = None) -> list[Issue]:
    pause = rules.get("online", {}).get("pause_seconds", 1.0)
    tasks = []
    for code, posts in posts_by_brand.items():
        for post in posts:
            for s in post.socials:
                if s.get("link"):
                    tasks.append((post, s["link"]))
    total = len(tasks) or 1
    issues: list[Issue] = []
    for i, (post, url) in enumerate(tasks):
        if should_stop and should_stop():
            break
        try:
            issues.extend(check_post_online(post, url, rules, vk_key))
        except Exception as e:  # noqa: BLE001
            issues.append(Issue(post.sheet, post.row, "Ссылка", Level.TECH,
                                "tech_online", f"Онлайн-проверка не сработала: {e}",
                                "", brand=post.brand, link=url))
        if progress_cb:
            progress_cb((i + 1) / total)
        time.sleep(pause)
    return issues
