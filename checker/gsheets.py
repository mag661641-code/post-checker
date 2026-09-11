"""Чтение реестра напрямую из Google-таблицы через сервисный аккаунт.

Подход: таблица скачивается из Google как .xlsx во временную память и
передаётся тому же загрузчику (loader.load_workbook), что и обычный файл.
Так сохраняется вся логика проверок (объединённые ячейки, серийные даты и т.п.).

Сервисному аккаунту достаточно доступа «Читатель» (Viewer) — сервис ничего
не изменяет в исходной таблице.

Библиотеки google-api-python-client и google-auth импортируются внутри функций,
чтобы модуль можно было импортировать даже там, где они не установлены.
"""
from __future__ import annotations

import io
import json
import re
from typing import Any

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


def coerce_service_account(info: Any) -> dict[str, Any]:
    """Привести ключ сервисного аккаунта к нормальному dict.

    Принимает:
      - dict (TOML-таблица `[gcp_service_account]`);
      - строку с JSON (когда вставлен весь файл-ключ целиком).
    Чинит `private_key`, если переносы строк остались как литеральные «\\n».
    """
    if isinstance(info, str):
        data = json.loads(info)
    elif isinstance(info, dict):
        data = dict(info)
    else:
        # объекты Streamlit Secrets ведут себя как dict
        data = {k: info[k] for k in info}
    pk = str(data.get("private_key", ""))
    if "\\n" in pk and "\n" not in pk:
        data["private_key"] = pk.replace("\\n", "\n")
    return data


def extract_sheet_id(url_or_id: str) -> str:
    """Достать ID таблицы из ссылки Google Sheets или принять готовый ID."""
    s = (url_or_id or "").strip()
    if not s:
        raise ValueError("Пустая ссылка на Google-таблицу.")
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_\-]+)", s)
    if m:
        return m.group(1)
    m = re.search(r"[?&]id=([a-zA-Z0-9_\-]+)", s)
    if m:
        return m.group(1)
    if re.fullmatch(r"[a-zA-Z0-9_\-]{20,}", s):
        return s
    raise ValueError("Не удалось распознать ссылку или ID Google-таблицы. "
                     "Скопируйте ссылку из адресной строки таблицы целиком.")


def download_as_xlsx(url_or_id: str, service_account_info: dict[str, Any]) -> bytes:
    """Скачать Google-таблицу как .xlsx (bytes) через сервисный аккаунт.

    service_account_info — содержимое JSON-ключа сервисного аккаунта (dict).
    """
    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(
            "Не установлены библиотеки для Google (google-api-python-client, "
            "google-auth). Добавьте их в requirements.txt."
        ) from e

    file_id = extract_sheet_id(url_or_id)
    creds = Credentials.from_service_account_info(
        coerce_service_account(service_account_info), scopes=[DRIVE_SCOPE])
    service = build("drive", "v3", credentials=creds, cache_discovery=False)

    request = service.files().export_media(fileId=file_id, mimeType=XLSX_MIME)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()
