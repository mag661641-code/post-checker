"""Хранение настроек в отдельной Google-таблице «Настройки проверки постов».

Чтобы не проектировать десяток листов, весь набор настроек хранится JSON-текстом
в одной ячейке A1 первого листа. Для пользователя это неважно: настройки он
редактирует в интерфейсе, а таблица — лишь надёжное хранилище (на Streamlit
Cloud файлы config/*.json обнуляются при перезапуске).

Сервисному аккаунту нужен доступ «Редактор» к этой таблице.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from . import gsheets

WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
CELL = "A1"
# Результаты проверки нейросетью храним в отдельной ячейке, чтобы даже при
# переполнении они не могли испортить основные настройки в A1.
AI_CELL = "A2"
AI_MAX_CHARS = 45000  # в ячейке Google Sheets лимит ~50 000 символов


def _service(sa: Any):
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_service_account_info(
        gsheets.coerce_service_account(sa), scopes=[WRITE_SCOPE])
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _first_sheet_title(svc, sid: str) -> str:
    meta = svc.spreadsheets().get(
        spreadsheetId=sid, fields="sheets.properties.title").execute()
    sheets = meta.get("sheets", [])
    return sheets[0]["properties"]["title"] if sheets else "Лист1"


def read_bundle(url: str, sa: Any) -> Optional[dict]:
    """Прочитать набор настроек из таблицы. None — если пусто/нет данных."""
    svc = _service(sa)
    sid = gsheets.extract_sheet_id(url)
    rng = f"'{_first_sheet_title(svc, sid)}'!{CELL}"
    res = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=rng).execute()
    vals = res.get("values", [])
    if not vals or not vals[0] or not str(vals[0][0]).strip():
        return None
    try:
        return json.loads(vals[0][0])
    except Exception:  # noqa: BLE001
        return None


def write_bundle(url: str, sa: Any, bundle: dict) -> None:
    """Записать набор настроек в таблицу (одной ячейкой)."""
    svc = _service(sa)
    sid = gsheets.extract_sheet_id(url)
    rng = f"'{_first_sheet_title(svc, sid)}'!{CELL}"
    body = {"values": [[json.dumps(bundle, ensure_ascii=False)]]}
    svc.spreadsheets().values().update(
        spreadsheetId=sid, range=rng, valueInputOption="RAW",
        body=body).execute()


def read_ai_cache(url: str, sa: Any) -> dict:
    """Прочитать сохранённые результаты проверки нейросетью ({} если пусто)."""
    svc = _service(sa)
    sid = gsheets.extract_sheet_id(url)
    rng = f"'{_first_sheet_title(svc, sid)}'!{AI_CELL}"
    res = svc.spreadsheets().values().get(
        spreadsheetId=sid, range=rng).execute()
    vals = res.get("values", [])
    if not vals or not vals[0] or not str(vals[0][0]).strip():
        return {}
    try:
        data = json.loads(vals[0][0])
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def write_ai_cache(url: str, sa: Any, cache: dict) -> None:
    """Записать результаты проверки нейросетью в отдельную ячейку.

    Если данных слишком много для одной ячейки — отбрасываем самые старые
    (первые по порядку добавления), пока не влезет."""
    items = list(cache.items())
    payload = json.dumps(dict(items), ensure_ascii=False)
    while len(payload) > AI_MAX_CHARS and len(items) > 1:
        drop = max(1, len(items) // 10)
        items = items[drop:]  # выбрасываем самые старые
        payload = json.dumps(dict(items), ensure_ascii=False)
    svc = _service(sa)
    sid = gsheets.extract_sheet_id(url)
    rng = f"'{_first_sheet_title(svc, sid)}'!{AI_CELL}"
    svc.spreadsheets().values().update(
        spreadsheetId=sid, range=rng, valueInputOption="RAW",
        body={"values": [[payload]]}).execute()
