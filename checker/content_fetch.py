"""Чтение текста поста из внешней ссылки: Google Документ или статья Дзен.

Нужно, когда в таблице стоит только ссылка (пост-документ или статья), а сам
текст — снаружи. Тогда его можно подгрузить и проверить нейросетью.

- Google Документ читается через Drive API сервисным аккаунтом (документ должен
  быть доступен этому аккаунту или открыт по ссылке).
- Дзен — обычная веб-страница; текст достаём из разметки (application/ld+json,
  поле articleBody). Получается не всегда — тогда честно сообщаем об этом.

Сеть и Google-библиотеки подгружаются лениво, чтобы модуль импортировался везде.
"""
from __future__ import annotations

import html as _html
import io
import json
import re
from typing import Any, Optional

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; PostChecker/1.0)"}


# ---------------------------------------------------------------------------
# Google Документ
# ---------------------------------------------------------------------------
def _doc_id(url: str) -> str:
    for pat in (r"/document/d/([a-zA-Z0-9_\-]+)",
                r"/file/d/([a-zA-Z0-9_\-]+)",
                r"[?&]id=([a-zA-Z0-9_\-]+)"):
        m = re.search(pat, url or "")
        if m:
            return m.group(1)
    return ""


def _doc_error(exc: Exception, sa: Any) -> str:
    from checker import gsheets
    s = str(exc).lower()
    if "404" in s or "not found" in s or "notfound" in s:
        return "Google Документ не найден — проверьте ссылку."
    if ("403" in s or "permission" in s or "forbidden" in s
            or "does not have access" in s):
        email = gsheets.sa_email(sa)
        return (f"Нет доступа к документу. Откройте к нему доступ для {email} "
                "(права «Читатель») или сделайте документ доступным по ссылке.")
    if "export" in s or "not exportable" in s or "only exportable" in s:
        return "Это не Google Документ — прочитать текст нельзя."
    return "Не удалось прочитать Google Документ."


def fetch_doc_text(url: str, sa: Any) -> tuple[str, Optional[str]]:
    """Вернуть (текст, ошибка). При успехе ошибка = None."""
    doc_id = _doc_id(url)
    if not doc_id:
        return "", "Не удалось разобрать ссылку на Google Документ."
    try:
        from checker import gsheets
        from googleapiclient.http import MediaIoBaseDownload
        drive = gsheets.drive_service(sa)
        req = drive.files().export_media(fileId=doc_id, mimeType="text/plain")
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()
        text = buf.getvalue().decode("utf-8", "replace").strip()
        if not text:
            return "", "Документ пустой или в нём нет текста."
        return text, None
    except Exception as exc:  # noqa: BLE001
        return "", _doc_error(exc, sa)


# ---------------------------------------------------------------------------
# Статья Дзен
# ---------------------------------------------------------------------------
def _find_key(data: Any, key: str) -> str:
    """Найти первое строковое значение по ключу в произвольном JSON."""
    if isinstance(data, dict):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v
        for val in data.values():
            r = _find_key(val, key)
            if r:
                return r
    elif isinstance(data, list):
        for val in data:
            r = _find_key(val, key)
            if r:
                return r
    return ""


def _clean_text(t: str) -> str:
    t = _html.unescape(t or "")
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def dzen_body_from_html(html: str) -> str:
    """Достать текст статьи из HTML Дзена (application/ld+json → articleBody)."""
    for m in re.finditer(
            r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>',
            html or "", re.S | re.I):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        body = _find_key(data, "articleBody")
        if body and len(body) > 200:
            return _clean_text(body)
    return ""


def fetch_dzen_text(url: str) -> tuple[str, Optional[str]]:
    try:
        import requests
        resp = requests.get(url, headers=_HEADERS, timeout=20,
                            allow_redirects=True)
    except Exception:  # noqa: BLE001
        return "", "Не удалось открыть статью в Дзене (нет связи)."
    if resp.status_code != 200:
        return "", f"Дзен вернул ошибку {resp.status_code}."
    body = dzen_body_from_html(resp.text)
    if body:
        return body, None
    return "", ("Не удалось автоматически прочитать текст статьи из Дзена. "
                "Вставьте текст статьи в таблицу, чтобы проверить.")


# ---------------------------------------------------------------------------
# Диспетчер
# ---------------------------------------------------------------------------
def fetch_link_text(url: str, sa: Any) -> tuple[str, str, Optional[str]]:
    """Вернуть (текст, тип, ошибка). тип: gdoc / dzen / other."""
    from checker import normalize as N
    kind = N.classify_link(url)
    if kind == "gdoc":
        if not sa:
            return "", kind, "Не подключён сервисный аккаунт Google."
        text, err = fetch_doc_text(url, sa)
        return text, kind, err
    if kind == "dzen":
        text, err = fetch_dzen_text(url)
        return text, kind, err
    return "", kind, ("Чтение текста поддерживается только для Google "
                      "Документов и статей Дзена.")
