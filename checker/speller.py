"""Проверка орфографии через API Яндекс.Спеллера.

Отдельный модуль: нужен интернет, поэтому проверка по умолчанию выключена.
При недоступности API — совет, без падения.
"""
from __future__ import annotations

import re
from typing import Any

import requests

from . import normalize as N
from .models import Issue, Level, PostRecord

SPELLER_URL = "https://speller.yandex.net/services/spellservice.json/checkText"


def _clean_for_speller(text: str) -> str:
    """Убрать ссылки, хэштеги и e-mail, чтобы не ловить ложные ошибки."""
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"#[\wА-Яа-яЁё]+", " ", text)
    text = re.sub(r"\S+@\S+", " ", text)
    return text


def check_post_spelling(post: PostRecord, whitelist: set[str],
                        timeout: int = 10) -> list[Issue]:
    text = _clean_for_speller(post.text)
    if not text.strip():
        return []
    try:
        resp = requests.post(
            SPELLER_URL,
            data={"text": text, "lang": "ru", "options": 512},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:  # noqa: BLE001
        return [Issue(
            post.sheet, post.row, "Пост", Level.ADVICE, "spell_unavailable",
            "Орфографию проверить не удалось (нет связи с сервисом Яндекс.Спеллер).",
            "Проверьте текст на опечатки вручную или повторите позже.",
            brand=post.brand, post_type=post.post_type,
        )]

    wl_lower = {w.lower() for w in whitelist}
    issues = []
    seen = set()
    for item in data:
        word = item.get("word", "")
        if not word or word.lower() in wl_lower or word in seen:
            continue
        seen.add(word)
        variants = ", ".join(item.get("s", [])) or "нет вариантов"
        issues.append(Issue(
            post.sheet, post.row, "Пост", Level.WARNING, "spell_error",
            f"Возможная опечатка: «{word}». Варианты: {variants}.",
            "Проверьте слово. Если это термин или марка стали — добавьте его "
            "в белый список в настройках.",
            brand=post.brand, post_type=post.post_type,
        ))
    return issues


def run_spelling(posts_by_brand: dict[str, list[PostRecord]], whitelist: set[str],
                 rules: dict, progress_cb=None) -> list[Issue]:
    timeout = rules.get("online", {}).get("timeout_seconds", 10)
    issues: list[Issue] = []
    all_posts = [(c, p) for c, ps in posts_by_brand.items() for p in ps if p.text.strip()]
    total = len(all_posts)
    unavailable_reported = False
    for i, (code, post) in enumerate(all_posts):
        res = check_post_spelling(post, whitelist, timeout)
        # если API упал — сообщим один раз и прекратим, чтобы не ждать
        if res and res[0].code == "spell_unavailable":
            if not unavailable_reported:
                issues.append(res[0])
                unavailable_reported = True
            break
        issues.extend(res)
        if progress_cb:
            progress_cb((i + 1) / total)
    return issues
