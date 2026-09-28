"""Запись значений обратно в Google-таблицу (пока — только даты постов).

Меняем ТОЛЬКО значение конкретной ячейки через Sheets API values().update.
Оформление, объединённые ячейки, выпадающие списки и ширины колонок при этом
не трогаются — API переписывает лишь содержимое адресованной ячейки.

Запись возможна только через сервисный аккаунт с доступом «Редактор»
(по публичной ссылке Google писать через API не даёт). Библиотеки Google
импортируются лениво — как и в gsheets.py, чтобы модуль грузился везде.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from . import gsheets

WRITE_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


def _service(sa: Any):
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_service_account_info(
        gsheets.coerce_service_account(sa), scopes=[WRITE_SCOPE])
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _col_letter(col0: int) -> str:
    """Буква колонки Excel по индексу с нуля (0 -> A, 1 -> B, ...)."""
    from openpyxl.utils import get_column_letter
    return get_column_letter(col0 + 1)


def cell_a1(sheet_title: str, row: int, col0: int) -> str:
    """Адрес ячейки в формате A1 с именем листа: 'СМУ'!B4."""
    return f"'{sheet_title}'!{_col_letter(col0)}{row}"


def set_date(url_or_id: str, sheet_title: str, row: int, col0: int,
             value: dt.date, sa: Any) -> None:
    """Записать дату в ячейку {лист}!{колонка}{строка}.

    valueInputOption=USER_ENTERED — Google сам распознаёт «дд.мм.гггг» как дату,
    поэтому числовой формат ячейки (dd.MM.yyyy) сохраняется. Запись идёт в
    верхнюю (левую) ячейку объединённого диапазона — так и нужно.
    """
    svc = _service(sa)
    sid = gsheets.extract_sheet_id(url_or_id)
    rng = cell_a1(sheet_title, row, col0)
    body = {"values": [[value.strftime("%d.%m.%Y")]]}
    svc.spreadsheets().values().update(
        spreadsheetId=sid, range=rng, valueInputOption="USER_ENTERED",
        body=body).execute()
