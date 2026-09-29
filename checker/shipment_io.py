"""Чтение Google Диска и проверка сайта для проверки картинок отгрузок.

Список файлов бренда берём через Drive API (сервисный аккаунт, доступ только на
чтение — тот же ключ, что и для таблицы). Проверка сайта — обычные HTTP-запросы.

Сеть и клиенты Google подгружаются лениво, чтобы модуль импортировался и без
установленных библиотек / без ключа.
"""
from __future__ import annotations

from typing import Any, Optional

_FOLDER_MIME = "application/vnd.google-apps.folder"
DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"


def _drive(sa: Any):
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    from .gsheets import coerce_service_account
    creds = Credentials.from_service_account_info(
        coerce_service_account(sa), scopes=[DRIVE_SCOPE])
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _list_recursive(service, folder_id: str, acc: list) -> list:
    """Файлы папки и всех подпапок (кроме корзины)."""
    page_token = None
    subfolders = []
    while True:
        resp = service.files().list(
            q="'%s' in parents and trashed = false" % folder_id,
            fields="nextPageToken, files(id, name, size, mimeType, webViewLink)",
            pageSize=1000, pageToken=page_token,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        for f in resp.get("files", []):
            if f.get("mimeType") == _FOLDER_MIME:
                subfolders.append(f["id"])
            else:
                acc.append(f)
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    for sub in subfolders:
        _list_recursive(service, sub, acc)
    return acc


def load_brand_drive(folder_id: str, sa: Any) -> dict:
    """Файлы из папки бренда: {base -> [{name, ext, size_kb, url}, ...]}."""
    service = _drive(sa)
    files = _list_recursive(service, folder_id, [])
    result: dict[str, list] = {}
    for f in files:
        name = f["name"]
        dot = name.rfind(".")
        base = name if dot == -1 else name[:dot]
        ext = "" if dot == -1 else name[dot + 1:]
        size_kb = round(int(f.get("size", 0)) / 1024) if f.get("size") else 0
        result.setdefault(base, []).append({
            "name": name, "ext": ext, "size_kb": size_kb,
            "url": f.get("webViewLink", ""),
        })
    return result


# ---------------------------------------------------------------------------
# Сайт
# ---------------------------------------------------------------------------
def build_site_queue(brand: str, expected: list[dict]) -> list[dict]:
    """Список ссылок бренда для проверки сайта (только http/https)."""
    import re
    q = []
    for e in expected:
        for u in (e.get("jpg_url", ""), e.get("webp_url", "")):
            if u and re.match(r"^https?://", u, re.IGNORECASE):
                q.append({"brand": brand, "name": e["name"], "row": e["row"],
                          "url": u})
    return q


def check_site(queue: list[dict], progress_cb=None) -> list:
    """Проверить ссылки. Возвращает список ImgProblem. queue —
    [{brand, name, row, url}, ...]. progress_cb(done, total) — для прогресса."""
    import requests
    from .shipment_images import evaluate_site_response

    problems = []
    total = len(queue)
    session = requests.Session()
    for i, item in enumerate(queue):
        status: Optional[int] = None
        headers: dict = {}
        try:
            resp = session.get(item["url"], allow_redirects=False, timeout=20,
                               stream=True)
            status = resp.status_code
            headers = dict(resp.headers)
            resp.close()
        except Exception:  # noqa: BLE001
            status, headers = None, {}
        problem = evaluate_site_response(status, headers, item["url"],
                                         item["brand"], item["name"], item["row"])
        if problem:
            problems.append(problem)
        if progress_cb:
            progress_cb(i + 1, total)
    return problems
