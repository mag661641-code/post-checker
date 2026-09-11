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
