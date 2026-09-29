"""Фаза 1 планирования: адрес ячейки для записи и колонка даты в PostRecord."""
import datetime as dt
from io import BytesIO

import openpyxl

from checker import loader as L
from checker import sheets_write as W


def test_cell_a1_column_letters():
    assert W.cell_a1("МПЭ", 2, 0) == "'МПЭ'!A2"
    assert W.cell_a1("СМУ", 4, 1) == "'СМУ'!B4"
    assert W.cell_a1("ИМП", 10, 27) == "'ИМП'!AB10"


def _brand_book() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "МПЭ"
    ws.append(["Дата", "Соцсеть", "Ссылка", "Пост", "Фото"])
    ws.append([dt.date(2026, 10, 5), "Telegram", "", "Текст поста про металл", ""])
    ws.append([dt.date(2026, 10, 9), "Вконтакте", "", "Другой пост о трубах", ""])
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_generate_slots_weekdays_types_holidays():
    from ui.planning_schedule import generate_slots
    rules = {"СМУ": {"weekdays": [0, 2, 4],
                     "types": ["Информационный", "Развлекательный"],
                     "skip_holidays": True}}
    holiday = dt.date(2026, 10, 7)  # среда
    slots = generate_slots(rules, 2026, 10, {holiday})
    # только пн/ср/пт
    assert {s["date"].weekday() for s in slots} == {0, 2, 4}
    # праздник пропущен
    assert all(s["date"] != holiday for s in slots)
    # рубрики чередуются по кругу
    assert slots[0]["type"] == "Информационный"
    assert slots[1]["type"] == "Развлекательный"
    assert slots[2]["type"] == "Информационный"
    # все слоты — проекта СМУ, id уникальны
    assert all(s["project"] == "СМУ" for s in slots)
    assert len({s["id"] for s in slots}) == len(slots)


def test_generate_slots_extra_posts():
    from ui.planning_schedule import generate_slots
    # основные посты — только по пятницам; «Поступление» дополнительно по вторникам
    rules = {"АПС": {"weekdays": [4], "types": ["Информационный"],
                     "skip_holidays": True,
                     "extra": [{"type": "Поступление", "weekdays": [1]}]}}
    slots = generate_slots(rules, 2026, 10, set())
    main = [s for s in slots if s["kind"] == "main"]
    extra = [s for s in slots if s["kind"] == "extra"]
    # основные — только пятницы
    assert {s["date"].weekday() for s in main} == {4}
    # дополнительные — только вторники, тип «Поступление»
    assert {s["date"].weekday() for s in extra} == {1}
    assert all(s["type"] == "Поступление" for s in extra)
    # id всех слотов уникальны (основной и доп. в один день не конфликтуют)
    assert len({s["id"] for s in slots}) == len(slots)


def test_generate_slots_main_and_extra_same_day():
    from ui.planning_schedule import generate_slots
    # основные по пятницам + доп. «Поступление» тоже по пятницам → два поста в день
    rules = {"СМУ": {"weekdays": [4], "types": ["Информационный"],
                     "skip_holidays": False,
                     "extra": [{"type": "Поступление", "weekdays": [4]}]}}
    slots = generate_slots(rules, 2026, 10, set())
    fridays = {s["date"] for s in slots}
    for d in fridays:
        kinds = sorted(s["kind"] for s in slots if s["date"] == d)
        assert kinds == ["extra", "main"]  # оба поста в один день


def test_loader_sets_date_col():
    lw = L.load_workbook(_brand_book())
    posts = lw.posts.get("МПЭ", [])
    assert len(posts) == 2
    # дата в колонке A (индекс 0) — планировщик должен знать это для записи
    assert all(p.date_col == 0 for p in posts)
    p = posts[0]
    assert p.date == dt.date(2026, 10, 5)
    assert W.cell_a1(p.sheet, p.row, p.date_col) == "'МПЭ'!A2"
