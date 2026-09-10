"""Чтение Excel-файла: объединённые ячейки, поиск колонок по названию,
группировка постов на листах брендов.

Читаем через openpyxl, чтобы корректно разворачивать объединённые ячейки.
Модуль не зависит от Streamlit.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any, Optional

import openpyxl

from . import normalize as N
from .models import PostRecord, RegistryRow

REGISTRY_SHEET = "Реестр постов"
BRAND_SHEETS = ["СМУ", "ИМП", "МПЭ", "МПИ", "АПС"]
HOLIDAYS_SHEET = "Обязательные праздники"
SHIPMENTS_SHEET = "Отгрузки"


@dataclass
class LoadedWorkbook:
    """Результат чтения файла."""
    sheet_names: list[str] = field(default_factory=list)
    registry: list[RegistryRow] = field(default_factory=list)
    posts: dict[str, list[PostRecord]] = field(default_factory=dict)   # по бренду-листу
    stats_comments: list[dict] = field(default_factory=list)           # блок «Комментарии»
    holidays_raw: list[dict] = field(default_factory=list)
    sheet_info: dict[str, dict] = field(default_factory=dict)          # для страницы «Загрузка»
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Разворачивание объединённых ячеек
# ---------------------------------------------------------------------------
def _build_grid(ws) -> list[list[Any]]:
    """Прочитать лист в матрицу значений, развернув объединённые ячейки."""
    return _build_grids(ws)[1]


def _build_grids(ws) -> tuple[list[list[Any]], list[list[Any]]]:
    """Вернуть (raw_grid, expanded_grid).

    raw_grid — как в файле (в объединённой ячейке заполнена только верхняя левая).
    expanded_grid — значение объединённой ячейки развёрнуто на весь диапазон.
    Raw нужен, чтобы находить начало группы поста (текст в «Пост» есть только
    в верхней строке объединённого блока).
    """
    max_row = ws.max_row or 0
    max_col = ws.max_column or 0
    raw = [[ws.cell(r + 1, c + 1).value for c in range(max_col)]
           for r in range(max_row)]
    expanded = [list(row) for row in raw]
    for mr in ws.merged_cells.ranges:
        top = expanded[mr.min_row - 1][mr.min_col - 1]
        for r in range(mr.min_row, mr.max_row + 1):
            for c in range(mr.min_col, mr.max_col + 1):
                expanded[r - 1][c - 1] = top
    return raw, expanded


def _find_header_row(grid: list[list[Any]], required: list[str],
                     scan: int = 6) -> Optional[int]:
    """Найти строку заголовка по наличию нужных названий колонок."""
    req = [r.strip().lower() for r in required]
    for i in range(min(scan, len(grid))):
        cells = [str(v).strip().lower() if v is not None else "" for v in grid[i]]
        hits = sum(1 for r in req if any(r == c or (r and r in c) for c in cells))
        if hits >= max(2, len(req) // 2):
            return i
    return None


def _column_map(header: list[Any]) -> dict[str, int]:
    """Сопоставить нормализованное имя колонки -> индекс (0-based)."""
    m: dict[str, int] = {}
    for idx, v in enumerate(header):
        if v is None:
            continue
        key = re.sub(r"\s+", " ", str(v)).strip().lower()
        if key and key not in m:
            m[key] = idx
    return m


def _get(colmap: dict[str, int], row: list[Any], *names: str) -> Any:
    for name in names:
        idx = colmap.get(name.strip().lower())
        if idx is not None and idx < len(row):
            return row[idx]
    return None


# ---------------------------------------------------------------------------
# Главный вход
# ---------------------------------------------------------------------------
def load_workbook(source) -> LoadedWorkbook:
    """source — путь к файлу, bytes или файловый объект Streamlit."""
    if isinstance(source, (bytes, bytearray)):
        source = BytesIO(source)
    wb = openpyxl.load_workbook(source, data_only=True)
    result = LoadedWorkbook(sheet_names=list(wb.sheetnames))

    for name in wb.sheetnames:
        ws = wb[name]
        result.sheet_info[name] = {"rows": ws.max_row, "cols": ws.max_column}

    if REGISTRY_SHEET in wb.sheetnames:
        try:
            result.registry = _load_registry(wb[REGISTRY_SHEET])
            result.sheet_info[REGISTRY_SHEET]["parsed"] = len(result.registry)
        except Exception as e:  # noqa: BLE001
            result.warnings.append(f"Лист «{REGISTRY_SHEET}»: {e}")

    for name in BRAND_SHEETS:
        if name in wb.sheetnames:
            try:
                posts, comments = _load_brand_sheet(wb[name], name)
                result.posts[name] = posts
                result.stats_comments.extend(comments)
                result.sheet_info[name]["parsed"] = len(posts)
            except Exception as e:  # noqa: BLE001
                result.warnings.append(f"Лист «{name}»: {e}")
                result.posts[name] = []

    if HOLIDAYS_SHEET in wb.sheetnames:
        try:
            result.holidays_raw = _load_holidays(wb[HOLIDAYS_SHEET])
        except Exception as e:  # noqa: BLE001
            result.warnings.append(f"Лист «{HOLIDAYS_SHEET}»: {e}")

    return result


# ---------------------------------------------------------------------------
# Реестр постов
# ---------------------------------------------------------------------------
def _load_registry(ws) -> list[RegistryRow]:
    grid = _build_grid(ws)
    hdr_i = _find_header_row(grid, ["бренд", "тип поста", "ссылка", "статус"])
    if hdr_i is None:
        raise ValueError("не найдена строка заголовка")
    colmap = _column_map(grid[hdr_i])
    rows: list[RegistryRow] = []
    for i in range(hdr_i + 1, len(grid)):
        row = grid[i]
        excel_row = i + 1
        brand = _clean(_get(colmap, row, "бренд"))
        links_raw = _get(colmap, row, "ссылка")
        status = _clean(_get(colmap, row, "статус"))
        ptype = _clean(_get(colmap, row, "тип поста", "тип"))
        # пустая строка целиком — пропускаем
        if not any([brand, status, ptype, links_raw]):
            continue
        rr = RegistryRow(
            row=excel_row,
            write_date_raw=_get(colmap, row, "дата написания"),
            pub_date_raw=_get(colmap, row, "дата публикации (план)",
                              "дата публикации"),
            brand=brand,
            executor=_clean(_get(colmap, row, "исполнитель")),
            post_type=ptype,
            links_raw=str(links_raw) if links_raw is not None else "",
            status=status,
        )
        rr.write_date, _ = N.parse_date(rr.write_date_raw)
        rr.pub_date, _ = N.parse_date(rr.pub_date_raw)
        rr.links = N.extract_links(rr.links_raw)
        rr.links_norm = [N.normalize_link(u) for u in rr.links]
        rows.append(rr)
    return rows


# ---------------------------------------------------------------------------
# Листы брендов
# ---------------------------------------------------------------------------
def _load_brand_sheet(ws, brand: str) -> tuple[list[PostRecord], list[dict]]:
    raw, grid = _build_grids(ws)
    hdr_i = _find_header_row(grid, ["соцсеть", "ссылка", "пост", "фото"])
    if hdr_i is None:
        raise ValueError("не найдена строка заголовка")
    colmap = _column_map(grid[hdr_i])
    post_idx = colmap.get("пост")

    date_key = "когда выложить" if "когда выложить" in colmap else "дата"

    posts: list[PostRecord] = []
    comments: list[dict] = []
    current: Optional[PostRecord] = None

    def flush():
        nonlocal current
        if current is not None:
            posts.append(current)
        current = None

    for i in range(hdr_i + 1, len(grid)):
        row = grid[i]
        excel_row = i + 1
        social = _clean(_get(colmap, row, "соцсеть"))
        link = _clean(_get(colmap, row, "ссылка"))
        text = _get(colmap, row, "пост")
        date_val = _get(colmap, row, date_key)
        ptype = _clean(_get(colmap, row, "тип"))
        photo = _clean(_get(colmap, row, "фото"))
        stat = _get(colmap, row, "статистика")
        executor = _clean(_get(colmap, row, "исполнитель"))

        # текст поста берём из «сырой» сетки: в объединённом блоке он есть
        # только в верхней строке — это и есть признак начала новой группы
        raw_text = raw[i][post_idx] if post_idx is not None and i < len(raw) else None

        # служебная строка с годом («2025», «2026») или месяцем
        if _is_service_row(row, colmap, date_val, social, link, raw_text):
            continue

        parsed_date, _ = N.parse_date(date_val)
        starts_new = bool(raw_text and str(raw_text).strip())

        if starts_new:
            flush()
            current = PostRecord(
                sheet=brand, row=excel_row, brand=brand,
                date=parsed_date, post_type=ptype,
                text=str(text) if text is not None else "",
                executor=executor, raw_rows=[excel_row],
            )
            if photo:
                current.photos.append(photo)
            if social or link:
                current.socials.append({"social": social, "link": link, "row": excel_row})
            _collect_stat_comment(stat, brand, excel_row, comments, current)
        else:
            if current is None:
                # строка-продолжение без начала — пропускаем
                continue
            current.raw_rows.append(excel_row)
            if social or link:
                current.socials.append({"social": social, "link": link, "row": excel_row})
            if photo:
                current.photos.append(photo)
            _collect_stat_comment(stat, brand, excel_row, comments, current)

    flush()
    return posts, comments


def _collect_stat_comment(stat: Any, brand: str, row: int,
                          comments: list[dict], post: PostRecord) -> None:
    """Комментарии руководителя из колонки «Статистика» (не число)."""
    if stat is None:
        return
    s = str(stat).strip()
    if not s:
        return
    # числа и «доли» — это статистика, а не комментарий
    if re.fullmatch(r"[\d\s.,%()+\-–—]+", s):
        return
    # заголовки служебных таблиц
    if s.lower() in {"статистика", "вконтакте", "одноклассники", "план", "факт"}:
        return
    comments.append({"brand": brand, "row": row, "text": s})
    post.stats_comments.append(s)


def _is_service_row(row, colmap, date_val, social, link, text) -> bool:
    """Служебная строка: только год/месяц без данных поста."""
    if social or link or text:
        return False
    if date_val is None:
        return True
    s = str(date_val).strip()
    if re.fullmatch(r"20\d\d(\.0)?", s):
        return True
    if re.fullmatch(r"[А-Яа-я]+\s+20\d\d", s):  # «Июнь 2025»
        return True
    return False


# ---------------------------------------------------------------------------
# Обязательные праздники
# ---------------------------------------------------------------------------
def _load_holidays(ws) -> list[dict]:
    grid = _build_grid(ws)
    hdr_i = _find_header_row(grid, ["месяц", "дата", "праздник", "тип"])
    if hdr_i is None:
        raise ValueError("не найдена строка заголовка")
    colmap = _column_map(grid[hdr_i])
    out: list[dict] = []
    for i in range(hdr_i + 1, len(grid)):
        row = grid[i]
        name = _clean(_get(colmap, row, "праздник"))
        if not name:
            continue
        out.append({
            "row": i + 1,
            "month": _clean(_get(colmap, row, "месяц")),
            "date_raw": _get(colmap, row, "дата"),
            "name": name,
            "type": _clean(_get(colmap, row, "тип")),
        })
    return out


def _clean(v: Any) -> str:
    if v is None:
        return ""
    return re.sub(r"\s+", " ", str(v)).strip()
