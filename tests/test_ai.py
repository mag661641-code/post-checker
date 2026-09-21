"""Тесты смысловой проверки нейросетью — только чистая логика, без сети."""
from checker import ai_review as A
from checker.models import Issue, Level
from checker import report as R


_SETTINGS = {"check_tone": True, "check_structure": True, "check_quality": True,
             "level": "advice", "max_issues": 5}


def test_drop_fabricated_numbers():
    text = "Труба 20х20, толщина 2 мм."
    raw = [{"category": "fact", "level": "advice", "title": "Толщина 22 мм?",
            "why": "проверьте", "what_to_do": "сверьте", "quote": ""}]
    # 22 нет в тексте и не в цитате -> замечание отбрасывается
    assert A.validate_issues(raw, text, _SETTINGS) == []


def test_number_in_quote_allowed():
    text = "Труба 20х20, толщина 2 мм."
    raw = [{"category": "quality", "level": "advice", "title": "Сухо про 20х20",
            "why": "нет пользы", "what_to_do": "добавьте выгоду",
            "quote": "Труба 20х20"}]
    out = A.validate_issues(raw, text, _SETTINGS)
    assert len(out) == 1


def test_fact_and_promise_forced_to_warning():
    text = "Отгрузим быстро."
    raw = [{"category": "promise", "level": "advice", "title": "Обещание срока",
            "why": "риск", "what_to_do": "сверьте с продажами", "quote": ""}]
    out = A.validate_issues(raw, text, _SETTINGS)
    assert out and out[0]["level"] == "warning"


def test_what_to_do_trimmed():
    text = "Текст."
    raw = [{"category": "quality", "level": "advice", "title": "Длинно",
            "why": "", "what_to_do": "x" * 400, "quote": ""}]
    out = A.validate_issues(raw, text, _SETTINGS)
    assert len(out[0]["what_to_do"]) <= 301


def test_category_toggle_off():
    text = "Текст."
    raw = [{"category": "tone", "level": "advice", "title": "Тон", "why": "",
            "what_to_do": "", "quote": ""}]
    s = dict(_SETTINGS, check_tone=False)
    assert A.validate_issues(raw, text, s) == []


def test_max_issues_limit():
    text = "Текст."
    raw = [{"category": "quality", "level": "advice", "title": "сухо",
            "why": "", "what_to_do": "", "quote": ""} for _ in range(10)]
    s = dict(_SETTINGS, max_issues=3)
    assert len(A.validate_issues(raw, text, s)) == 3


def test_report_source():
    ai = Issue("СМУ", 1, "Пост", Level.ADVICE, "ai_quality", "сухо")
    rule = Issue("СМУ", 1, "Пост", Level.ERROR, "text_placeholder", "заглушка")
    assert R._issue_source(ai) == "Нейросеть"
    assert R._issue_source(rule) == "Правило"
