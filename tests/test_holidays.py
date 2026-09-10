import datetime as dt

from checker import holidays as H


def test_fixed_date():
    assert H.resolve_holiday_date(dt.datetime(2026, 3, 8), "Март", 2026) == \
        dt.date(2026, 3, 8)


def test_founding_date_yearly():
    # «30 мая 2011 год» -> повторяется ежегодно
    assert H.resolve_holiday_date("30 мая 2011 год", "Май", 2026) == \
        dt.date(2026, 5, 30)


def test_floating_last_sunday_september():
    d = H.resolve_holiday_date("последнее воскресенье сентября", "Сентябрь", 2026)
    assert d.month == 9 and d.weekday() == 6
    # последнее воскресенье сентября 2026 — 27.09.2026
    assert d == dt.date(2026, 9, 27)


def test_floating_third_sunday_july():
    d = H.resolve_holiday_date("3-е воскресенье июля", "Июль", 2026)
    assert d.month == 7 and d.weekday() == 6
    assert d == dt.date(2026, 7, 19)


def test_corporate_brand_detected():
    raw = [{"row": 7, "month": "Май", "date_raw": "30 мая 2011 год",
            "name": "День рождения СМУ", "type": "Корпоративные"}]
    cal = H.build_holiday_calendar(raw, 2026)
    assert cal[0]["corp_brand"] == "СМУ"
