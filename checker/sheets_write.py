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


# ---------------------------------------------------------------------------
# Вставка блоков графика (шаг 2b, часть 2: запись новых постов)
# ---------------------------------------------------------------------------
def sheet_gid(url_or_id: str, sheet_title: str, sa: Any) -> int:
    """gid (sheetId) листа по названию — нужен для координат batchUpdate."""
    meta = gsheets.get_metadata(url_or_id, sa)
    for s in meta["sheets"]:
        if s["title"] == sheet_title:
            if s["gid"] is None:
                raise ValueError(f"У листа «{sheet_title}» нет gid.")
            return int(s["gid"])
    raise ValueError(f"Лист «{sheet_title}» не найден в таблице.")


def build_insert_requests(insertions: list, gid: int, template_row: int,
                          template_size: int, date_col: int,
                          type_col: Any, ncols: int) -> list[dict]:
    """Собрать запросы batchUpdate для вставки блоков-постов.

    insertions — список объектов с полями .date, .post_type, .at_row (1-based,
    строка исходного листа, ПЕРЕД которой вставляем), .size, .new_header.
    Строки нумеруются с исходного листа; вставки применяются сверху вниз по
    самой таблице, поэтому здесь мы раскладываем их по возрастанию at_row и
    ведём накопительный сдвиг: каждая вставка сдвигает вниз всё, что ниже, в том
    числе строку-шаблон и точки следующих вставок.

    Для каждого поста: insertDimension (size строк) → copyPaste форматов и
    объединений из шаблона → запись даты и типа. Для нового месяца добавляется
    строка-заголовок (объединённая на всю ширину) над блоком.

    Возвращает список request-ов в порядке применения. Функция чистая (без
    обращения к сети) — её удобно проверять тестом.
    """
    # порядок: сверху вниз; при равном at_row — по дате (раньше выше)
    items = sorted(insertions, key=lambda x: (x.at_row, x.date))
    reqs: list[dict] = []
    shift = 0                 # сколько строк уже вставлено выше по листу
    tr = template_row         # текущее положение строки-шаблона
    ncols = max(ncols, 1)

    def _insert_rows(start0: int, count: int) -> None:
        reqs.append({"insertDimension": {
            "range": {"sheetId": gid, "dimension": "ROWS",
                      "startIndex": start0, "endIndex": start0 + count},
            "inheritFromBefore": start0 > 0}})

    def _copy_format(src_start0: int, dst_start0: int, count: int) -> None:
        reqs.append({"copyPaste": {
            "source": {"sheetId": gid, "startRowIndex": src_start0,
                       "endRowIndex": src_start0 + count,
                       "startColumnIndex": 0, "endColumnIndex": ncols},
            "destination": {"sheetId": gid, "startRowIndex": dst_start0,
                            "endRowIndex": dst_start0 + count,
                            "startColumnIndex": 0, "endColumnIndex": ncols},
            "pasteType": "PASTE_FORMAT"}})

    def _set_text(row0: int, col0: int, text: str) -> None:
        reqs.append({"updateCells": {
            "range": {"sheetId": gid, "startRowIndex": row0,
                      "endRowIndex": row0 + 1, "startColumnIndex": col0,
                      "endColumnIndex": col0 + 1},
            "rows": [{"values": [{"userEnteredValue": {"stringValue": text}}]}],
            "fields": "userEnteredValue"}})

    def _merge_header(row0: int) -> None:
        reqs.append({"mergeCells": {
            "range": {"sheetId": gid, "startRowIndex": row0,
                      "endRowIndex": row0 + 1, "startColumnIndex": 0,
                      "endColumnIndex": ncols},
            "mergeType": "MERGE_ALL"}})

    for it in items:
        base = it.at_row + shift         # 1-based строка вставки с учётом сдвига
        added = (1 if it.new_header else 0) + it.size
        below = base <= tr               # шаблон ниже точки вставки — сместится
        start0 = base - 1                # 0-based для API

        if it.new_header:
            _insert_rows(start0, 1)
            _set_text(start0, 0, it.new_header)
            _merge_header(start0)
            start0 += 1

        _insert_rows(start0, it.size)
        # к моменту copyPaste обе вставки уже сделаны; если шаблон был ниже —
        # он сдвинулся вниз на все added строк этой итерации. Если образца нет
        # (template_size<=0) — копировать нечего, оставляем формат по умолчанию.
        if template_size > 0:
            src0 = (tr - 1) + (added if below else 0)
            _copy_format(src0, start0, min(it.size, template_size))
        _set_text(start0, date_col, it.date.strftime("%d.%m.%Y"))
        if type_col is not None and it.post_type:
            _set_text(start0, int(type_col), it.post_type)

        if below:
            tr += added
        shift += added
    return reqs


def apply_insertions(url_or_id: str, requests: list[dict], sa: Any) -> None:
    """Выполнить готовые запросы batchUpdate над таблицей (реальная запись)."""
    if not requests:
        return
    svc = _service(sa)
    sid = gsheets.extract_sheet_id(url_or_id)
    svc.spreadsheets().batchUpdate(
        spreadsheetId=sid, body={"requests": requests}).execute()
