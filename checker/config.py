"""Загрузка и сохранение конфигурации (бренды, правила, белый список).

Все настройки лежат в папке config/ и редактируются пользователем через
страницу «Настройки». Здесь только чтение/запись JSON и текстовых файлов.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
BRANDS_PATH = CONFIG_DIR / "brands.json"
RULES_PATH = CONFIG_DIR / "rules.json"
WHITELIST_PATH = CONFIG_DIR / "whitelist.txt"


def _read_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_brands() -> dict[str, Any]:
    return _read_json(BRANDS_PATH)


def load_rules() -> dict[str, Any]:
    return _read_json(RULES_PATH)


def load_whitelist() -> set[str]:
    words: set[str] = set()
    if WHITELIST_PATH.exists():
        for line in WHITELIST_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                words.add(line)
    return words


def save_brands(data: dict[str, Any]) -> None:
    _write_json(BRANDS_PATH, data)


def save_rules(data: dict[str, Any]) -> None:
    _write_json(RULES_PATH, data)


def save_whitelist(words: list[str] | set[str]) -> None:
    header = ("# Белый список слов для проверки орфографии.\n"
              "# Одно слово или выражение на строку.\n")
    body = "\n".join(sorted({w.strip() for w in words if w.strip()}))
    WHITELIST_PATH.write_text(header + body + "\n", encoding="utf-8")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def load_all() -> dict[str, Any]:
    """Единая точка загрузки всей конфигурации."""
    return {
        "brands": load_brands(),
        "rules": load_rules(),
        "whitelist": load_whitelist(),
    }


# --- значения по умолчанию для кнопки «Сбросить к стандартным» ---
_DEFAULTS_CACHE: dict[str, Any] = {}


def snapshot_defaults() -> None:
    """Запомнить текущие файлы как эталон (вызывается один раз при первом запуске)."""
    if not _DEFAULTS_CACHE:
        _DEFAULTS_CACHE["brands"] = deepcopy(load_brands())
        _DEFAULTS_CACHE["rules"] = deepcopy(load_rules())
        _DEFAULTS_CACHE["whitelist"] = sorted(load_whitelist())


def get_default(name: str) -> Any:
    snapshot_defaults()
    return deepcopy(_DEFAULTS_CACHE.get(name))
