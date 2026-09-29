"""Сборка запросов batchUpdate для вставки блоков графика (без сети)."""
import datetime as dt

from checker import schedule_plan as SP
from checker import sheets_write as W


def _ins(at, date, size=2, typ="Информационный", header=None):
    return SP.Insertion("МПЭ", date, typ, at, size, new_header=header)


def _kinds(reqs):
    return [next(iter(r)) for r in reqs]


def test_single_insert_existing_section():
    reqs = W.build_insert_requests(
        [_ins(5, dt.date(2026, 9, 10))], gid=0, template_row=5,
        template_size=2, date_col=0, type_col=5, ncols=8)
    assert _kinds(reqs) == ["insertDimension", "copyPaste", "updateCells",
                            "updateCells"]
    ins = reqs[0]["insertDimension"]["range"]
    assert (ins["startIndex"], ins["endIndex"]) == (4, 6)  # 2 строки перед стр.5
    # шаблон был на стр.5 и сдвинулся вниз на 2 → копируем с 0-based 6
    cp = reqs[1]["copyPaste"]
    assert cp["source"]["startRowIndex"] == 6
    assert cp["destination"]["startRowIndex"] == 4
    assert cp["pasteType"] == "PASTE_FORMAT"
    # дата пишется в колонку 0, тип — в колонку 5
    assert reqs[2]["updateCells"]["range"]["startColumnIndex"] == 0
    assert reqs[3]["updateCells"]["range"]["startColumnIndex"] == 5
    assert (reqs[2]["updateCells"]["rows"][0]["values"][0]
            ["userEnteredValue"]["stringValue"] == "10.09.2026")


def test_new_month_adds_merged_header():
    reqs = W.build_insert_requests(
        [_ins(7, dt.date(2026, 10, 5), header="Октябрь 2026")], gid=3,
        template_row=5, template_size=2, date_col=0, type_col=5, ncols=8)
    assert _kinds(reqs)[:3] == ["insertDimension", "updateCells", "mergeCells"]
    # заголовок объединён на всю ширину
    mc = reqs[2]["mergeCells"]["range"]
    assert (mc["startColumnIndex"], mc["endColumnIndex"]) == (0, 8)
    assert (reqs[1]["updateCells"]["rows"][0]["values"][0]
            ["userEnteredValue"]["stringValue"] == "Октябрь 2026")
    # шаблон выше точки вставки → копируется без сдвига (0-based 4)
    cp = next(r for r in reqs if "copyPaste" in r)["copyPaste"]
    assert cp["source"]["startRowIndex"] == 4


def test_two_inserts_shift_accumulates():
    # два поста перед существующим (оба at_row=5): раньше по дате должен встать выше
    reqs = W.build_insert_requests(
        [_ins(5, dt.date(2026, 9, 12)), _ins(5, dt.date(2026, 9, 10))],
        gid=0, template_row=5, template_size=2, date_col=0, type_col=5, ncols=8)
    inserts = [r["insertDimension"]["range"]["startIndex"]
               for r in reqs if "insertDimension" in r]
    # первая вставка на 0-based 4, вторая (с учётом сдвига +2) — на 0-based 6
    assert inserts == [4, 6]
    dates = [r["updateCells"]["rows"][0]["values"][0]["userEnteredValue"]
             ["stringValue"] for r in reqs
             if "updateCells" in r and r["updateCells"]["range"]["startColumnIndex"] == 0]
    assert dates == ["10.09.2026", "12.09.2026"]
