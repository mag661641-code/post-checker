"""Чтение реестра из Google-таблицы (сервисный аккаунт или публичная ссылка).

Таблица скачивается как .xlsx и передаётся тому же загрузчику на openpyxl,
поэтому логика проверок не меняется. Дополнительно через Sheets API берём
название таблицы и gid листов — для ссылок «Открыть в таблице».

Библиотеки google-api-python-client / google-auth импортируются внутри функций,
чтобы модуль импортировался и там, где их нет.
"""
from __future__ import annotations

import io
import json
import re
from typing import Any, Optional

import requests

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GSHEET_MIME = "application/vnd.google-apps.spreadsheet"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly"
SCOPES = [DRIVE_SCOPE, SHEETS_SCOPE]

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PostChecker/1.0)"}


# ---------------------------------------------------------------------------
# Ключ сервисного аккаунта
# ---------------------------------------------------------------------------
def coerce_service_account(info: Any) -> dict[str, Any]:
    """Привести ключ сервисного аккаунта к dict (принимает dict или JSON-строку)."""
    if isinstance(info, str):
        data = json.loads(info)
    elif isinstance(info, dict):
        data = dict(info)
    else:
        data = {k: info[k] for k in info}
    pk = str(data.get("private_key", ""))
    if "\\n" in pk and "\n" not in pk:
        data["private_key"] = pk.replace("\\n", "\n")
    return data


def sa_email(info: Any) -> str:
    try:
        return coerce_service_account(info).get("client_email", "")
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Разбор ссылки
# ---------------------------------------------------------------------------
def extract_sheet_id(url_or_id: str) -> str:
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
    raise ValueError("not_a_url")


def is_probably_xlsx_link(url: str) -> bool:
    return "rtpof=true" in (url or "")


# ---------------------------------------------------------------------------
# Клиенты Google
# ---------------------------------------------------------------------------
def _clients(info: Any):
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_service_account_info(
        coerce_service_account(info), scopes=SCOPES)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    return drive, sheets


# ---------------------------------------------------------------------------
# Метаданные и скачивание
# ---------------------------------------------------------------------------
def get_metadata(url_or_id: str, info: Any) -> dict[str, Any]:
    """Название таблицы и листы (title, gid, rows) через Sheets API."""
    _, sheets = _clients(info)
    sid = extract_sheet_id(url_or_id)
    meta = sheets.spreadsheets().get(
        spreadsheetId=sid,
        fields="properties.title,sheets.properties(title,sheetId,"
               "gridProperties.rowCount)").execute()
    out = {"title": meta.get("properties", {}).get("title", ""), "sheets": []}
    for s in meta.get("sheets", []):
        p = s.get("properties", {})
        out["sheets"].append({
            "title": p.get("title", ""),
            "gid": p.get("sheetId"),
            "rows": p.get("gridProperties", {}).get("rowCount"),
        })
    return out


def download_service_account(url_or_id: str, info: Any) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload
    drive, _ = _clients(info)
    sid = extract_sheet_id(url_or_id)
    request = drive.files().export_media(fileId=sid, mimeType=XLSX_MIME)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


# обратная совместимость со старым интерфейсом
def download_as_xlsx(url_or_id: str, service_account_info: Any) -> bytes:
    return download_service_account(url_or_id, service_account_info)


def download_public(url_or_id: str) -> bytes:
    """Скачать таблицу по публичной ссылке (доступ «у кого есть ссылка»)."""
    sid = extract_sheet_id(url_or_id)
    url = f"https://docs.google.com/spreadsheets/d/{sid}/export?format=xlsx"
    resp = requests.get(url, headers=_HEADERS, timeout=30, allow_redirects=True)
    data = resp.content
    if not data[:2] == b"PK":
        raise PermissionError("public_no_access")
    return data


def fetch_text_links(url_or_id: str, sheet_title: str, info: Any) -> dict[int, list[str]]:
    """Гиперссылки-анкоры внутри ячеек листа: {номер_строки_Excel: [uri, ...]}.

    Собирает ссылки трёх видов, которые не видны при выгрузке в .xlsx:
    целую ссылку ячейки (hyperlink), формулу HYPERLINK(...) и частичные
    ссылки на фрагменты текста (textFormatRuns → link.uri).
    """
    _, sheets = _clients(info)
    sid = extract_sheet_id(url_or_id)
    res = sheets.spreadsheets().get(
        spreadsheetId=sid, ranges=[sheet_title], includeGridData=True,
        fields=("sheets(data(rowData(values(hyperlink,"
                "userEnteredValue(formulaValue),"
                "textFormatRuns(format(link(uri)))))))")).execute()
    out: dict[int, list[str]] = {}
    for sh in res.get("sheets", []):
        for data in sh.get("data", []):
            for i, rd in enumerate(data.get("rowData", [])):
                links: list[str] = []
                for cell in rd.get("values", []) or []:
                    h = cell.get("hyperlink")
                    if h:
                        links.append(h)
                    fv = cell.get("userEnteredValue", {}).get("formulaValue")
                    if fv:
                        links.extend(re.findall(r'HYPERLINK\(\s*"([^"]+)"', fv,
                                                re.IGNORECASE))
                    for run in cell.get("textFormatRuns", []) or []:
                        uri = run.get("format", {}).get("link", {}).get("uri")
                        if uri:
                            links.append(uri)
                if links:
                    out[i + 1] = links
    return out


# ---------------------------------------------------------------------------
# Ссылка на ячейку
# ---------------------------------------------------------------------------
def open_in_sheet_url(sheet_id: str, gid: Optional[Any], row: Optional[int]) -> str:
    base = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    if gid is None:
        return base
    frag = f"#gid={gid}"
    if row:
        frag += f"&range=A{row}"
    return base + frag


# ---------------------------------------------------------------------------
# Проверка подключения
# ---------------------------------------------------------------------------
def test_connection(url: str, method: str, info: Any,
                    expected_sheets: Optional[list[str]] = None) -> dict[str, Any]:
    """Проверить подключение. Возвращает понятный структурированный результат.

    Ключи: ok, error, message, title, sheets, sa_email.
    """
    res = {"ok": False, "error": None, "message": "", "title": "",
           "sheets": [], "sa_email": sa_email(info) if info else ""}
    try:
        sid = extract_sheet_id(url)
    except ValueError:
        res["error"] = "not_a_url"
        res["message"] = "Это не ссылка на Google-таблицу."
        return res

    if is_probably_xlsx_link(url):
        res["error"] = "is_xlsx"
        res["message"] = ("Это Excel-файл на Google Диске, а не Google-таблица. "
                          "Откройте его и выберите «Файл → Сохранить как Google "
                          "Таблицы», затем вставьте новую ссылку.")
        return res

    if method == "public":
        try:
            data = download_public(sid)
        except PermissionError:
            res["error"] = "public_no_access"
            res["message"] = ("Нет доступа по ссылке: включите доступ «Все, у кого "
                              "есть ссылка».")
            return res
        except Exception:  # noqa: BLE001
            res["error"] = "no_access"
            res["message"] = "Не удалось скачать таблицу по ссылке."
            return res
        res["ok"] = True
        res["message"] = "Таблица доступна по ссылке."
        return _check_expected(res, expected_sheets, from_bytes=data)

    # способ А — сервисный аккаунт
    if not info:
        res["error"] = "no_sa_key"
        res["message"] = "Ключ сервисного аккаунта не добавлен в секреты."
        return res
    try:
        from googleapiclient.errors import HttpError
    except Exception:  # noqa: BLE001
        HttpError = Exception  # type: ignore
    try:
        # проверить тип файла
        drive, _ = _clients(info)
        finfo = drive.files().get(fileId=sid, fields="mimeType,name",
                                  supportsAllDrives=True).execute()
        if finfo.get("mimeType") != GSHEET_MIME:
            res["error"] = "is_xlsx"
            res["message"] = ("Это Excel-файл на Google Диске, а не Google-таблица. "
                              "Откройте его и выберите «Файл → Сохранить как Google "
                              "Таблицы», затем вставьте новую ссылку.")
            return res
        meta = get_metadata(sid, info)
    except HttpError as e:  # type: ignore
        code, message = classify_http_error(e)
        res["error"] = code
        if code == "no_access":
            res["message"] = (
                f"Нет доступа к таблице. Откройте доступ для адреса "
                f"{res['sa_email']} с правами «Читатель». Возможно, администратор "
                f"Google Workspace запрещает доступ для внешних адресов — тогда "
                f"используйте публичную ссылку.")
        else:
            res["message"] = message
        return res
    except Exception as e:  # noqa: BLE001
        res["error"] = "no_access"
        res["message"] = f"Не удалось подключиться: {e}"
        return res

    res["ok"] = True
    res["title"] = meta["title"]
    res["sheets"] = meta["sheets"]
    return _check_expected(res, expected_sheets)


def classify_http_error(e: Exception) -> tuple[str, str]:
    """Разобрать ошибку Google API. Возвращает (код, понятное сообщение)."""
    status = getattr(getattr(e, "resp", None), "status", None)
    content = getattr(e, "content", b"") or b""
    try:
        payload = json.loads(content)
    except Exception:  # noqa: BLE001
        payload = {}
    err = payload.get("error", {}) if isinstance(payload, dict) else {}
    msg = err.get("message", "") if isinstance(err, dict) else ""
    reason = ""
    if isinstance(err, dict) and err.get("errors"):
        reason = err["errors"][0].get("reason", "")

    api_disabled = (reason == "accessNotConfigured"
                    or "has not been used in project" in msg
                    or "SERVICE_DISABLED" in str(payload))
    if api_disabled:
        url_m = re.search(r"https://console\.[^\s\"']+", msg)
        which = ("Google Sheets API" if "sheets" in msg.lower()
                 else "Google Drive API" if "drive" in msg.lower()
                 else "нужный Google API")
        hint = (f"Не включён {which} в проекте. Откройте ссылку, нажмите Enable "
                f"и подождите 1–2 минуты, затем повторите."
                + (f" Ссылка: {url_m.group(0)}" if url_m else ""))
        return "api_disabled", hint
    if status == 404:
        return "not_found", "Таблица не найдена или удалена."
    return "no_access", ""


def _check_expected(res: dict, expected: Optional[list[str]],
                    from_bytes: Optional[bytes] = None) -> dict:
    if from_bytes is not None:
        # для публичной ссылки листы читаем из xlsx
        try:
            import openpyxl
            wb = openpyxl.load_workbook(io.BytesIO(from_bytes), read_only=True)
            res["sheets"] = [{"title": n, "gid": None, "rows": None}
                             for n in wb.sheetnames]
        except Exception:  # noqa: BLE001
            pass
    if expected:
        names = {s["title"] for s in res["sheets"]}
        missing = [e for e in expected if e not in names]
        if missing:
            res["ok"] = False
            res["error"] = "missing_sheets"
            res["message"] = ("Не найдены нужные листы: "
                              + ", ".join(f"«{m}»" for m in missing)
                              + ". Проверьте, не переименованы ли они.")
    return res
