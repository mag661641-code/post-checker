"""План вставки постов графика в лист бренда (шаг 2b, часть 1: расчёт, без записи).

Разбирает лист бренда (колонки, размер блока поста, разделы месяцев, шаблонный
блок) и считает, КУДА вставить каждый новый пост: в раздел нужного месяца, в
порядке дат; если раздела месяца нет — пометить, что нужен заголовок. Сама
запись в таблицу — отдельным модулем; здесь только план и предпросмотр.

Работает на openpyxl-листе (из выгрузки .xlsx), чтобы план можно было
посчитать и проверить без доступа на запись.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from . import loader as L
from . import normalize as N

_MONTHS = {"январь": 1, "февраль": 2, "март": 3, "апрель": 4, "май": 5,
           "июнь": 6, "июль": 7, "август": 8, "сентябрь": 9, "октябрь": 10,
           "ноябрь": 11, "декабрь": 12}
_MONTH_RE = re.compile(r"([А-Яа-я]+)\s+(20\d\d)")


def _month_of_label(text: Any) -> Optional[tuple[int, int]]:
    """«Октябрь 2026» -> (2026, 10). Иначе None."""
    m = _MONTH_RE.search(str(text or ""))
    if not m:
        return None
    mon = _MONTHS.get(m.group(1).strip().lower())
    if not mon:
        return None
    return int(m.group(2)), mon


@dataclass
class Block:
    """Блок поста: первая строка (Excel, 1-based) и число строк."""
    row: int
    size: int
    date: Optional[dt.date]


@dataclass
class Section:
    """Раздел месяца: строка-заголовок и (year, month)."""
    header_row: int
    year: int
    month: int


@dataclass
class BrandLayout:
    brand: str
    header_row: int
    date_col: int          # 0-based
    type_col: Optional[int]
    block_size: int        # типовое число строк на пост (из шаблона)
    template: Optional[Block]      # существующий блок-образец для копирования
    ncols: int = 0         # ширина таблицы (число колонок) — для копий и заголовков
    sections: list[Section] = field(default_factory=list)
    posts: list[Block] = field(default_factory=list)   # существующие посты с датой


@dataclass
class Insertion:
    brand: str
    date: dt.date
    post_type: str
    at_row: int            # строка, ПЕРЕД которой вставляем (в исходной нумерации)
    size: int
    new_header: Optional[str] = None   # текст заголовка месяца, если его надо создать


# ---------------------------------------------------------------------------
def parse_layout(ws, brand: str) -> BrandLayout:
    raw, grid = L._build_grids(ws)
    hdr = L._find_header_row(grid, ["соцсеть", "ссылка", "пост", "фото"])
    if hdr is None:
        raise ValueError(f"{brand}: не найден заголовок")
    colmap = L._column_map(grid[hdr])

    # колонка даты — как в загрузчике (по названию или по содержимому)
    date_key = next((n for n in L.DATE_COL_NAMES if n in colmap), None)
    date_col = colmap.get(date_key) if date_key else None
    if date_col is None or L._count_dates(grid, hdr, date_col) < 3:
        alt = L._detect_date_column(grid, hdr)
        if alt is not None:
            date_col = alt
    if date_col is None:
        raise ValueError(f"{brand}: не найдена колонка даты")
    type_col = colmap.get("тип")

    # разделы месяцев — широкие объединённые строки с текстом «Месяц ГГГГ»
    sections: list[Section] = []
    for mr in ws.merged_cells.ranges:
        if (mr.min_row == mr.max_row and mr.min_col <= date_col + 1
                and mr.max_col >= date_col + 2):
            ym = _month_of_label(ws.cell(mr.min_row, mr.min_col).value)
            if ym:
                sections.append(Section(mr.min_row, ym[0], ym[1]))
    sections.sort(key=lambda s: (s.year, s.month))

    # блоки постов: объединённые диапазоны в колонке даты с реальной датой
    posts: list[Block] = []
    for mr in ws.merged_cells.ranges:
        if mr.min_col <= date_col + 1 <= mr.max_col and mr.min_row > hdr + 1:
            val = ws.cell(mr.min_row, date_col + 1).value
            d, _ = N.parse_date(val)
            if d is not None:
                posts.append(Block(mr.min_row, mr.max_row - mr.min_row + 1, d))
    posts.sort(key=lambda b: b.row)

    # типовой размер блока и шаблон — по самому частому размеру среди постов
    if posts:
        from collections import Counter
        size = Counter(b.size for b in posts).most_common(1)[0][0]
        template = next((b for b in reversed(posts) if b.size == size), posts[-1])
        block_size = size
    else:
        block_size, template = 1, None

    ncols = max((len(r) for r in grid[hdr:]), default=len(grid[hdr]))
    return BrandLayout(brand, hdr, date_col, type_col, block_size, template,
                       ncols, sections, posts)


def _section_bounds(layout: BrandLayout, year: int, month: int,
                    total_rows: int) -> Optional[tuple[int, int]]:
    """Строки (первая_контента, последняя_контента) раздела месяца или None."""
    sec = next((s for s in layout.sections
                if s.year == year and s.month == month), None)
    if not sec:
        return None
    later = [s.header_row for s in layout.sections if s.header_row > sec.header_row]
    end = (min(later) - 1) if later else total_rows
    return sec.header_row + 1, end


def plan_insertions(layout: BrandLayout, slots: list[dict], total_rows: int
                    ) -> list[Insertion]:
    """slots: [{date: date, type: str}] одного бренда. Возвращает вставки в
    порядке дат. at_row — строка исходного листа, перед которой встанет пост."""
    slots = sorted(slots, key=lambda s: s["date"])
    out: list[Insertion] = []
    size = layout.block_size
    for s in slots:
        d: dt.date = s["date"]
        bounds = _section_bounds(layout, d.year, d.month, total_rows)
        if bounds:
            lo, hi = bounds
            # посты этого раздела, по возрастанию строки
            in_sec = [b for b in layout.posts if lo <= b.row <= hi and b.date]
            at = None
            for b in sorted(in_sec, key=lambda b: b.row):
                if b.date and b.date > d:
                    at = b.row
                    break
            if at is None:
                at = hi + 1  # в конец раздела
            out.append(Insertion(layout.brand, d, s.get("type", ""), at, size))
        else:
            # раздела месяца нет — создать заголовок в хронологическом месте
            later = [sec for sec in layout.sections
                     if (sec.year, sec.month) > (d.year, d.month)]
            if later:
                at = min(later, key=lambda s: s.header_row).header_row
            else:
                at = total_rows + 1
            label = f"{[k for k, v in _MONTHS.items() if v == d.month][0].capitalize()} {d.year}"
            out.append(Insertion(layout.brand, d, s.get("type", ""), at, size,
                                 new_header=label))
    return out
