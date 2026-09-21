"""Тесты смысловой проверки нейросетью — только чистая логика, без сети."""
from checker import ai_review as A
from checker.models import Issue, Level
from checker import report as R


_SETTINGS = {"check_tone": True, "check_structure": True, "check_quality": True,
             "level": "advice", "max_issues": 5}


def test_drop_fabricated_numbers():
    text = "Труба 20х20, толщина 2 мм."
    raw = [{"category": "fact", "level": "advice", "title": "Толщина 22 мм?",
            "why": "проверьте", "fragment": "", "suggestions": []}]
    # 22 нет в тексте и не во фрагменте -> замечание отбрасывается
    assert A.validate_issues(raw, text, _SETTINGS) == []


def test_number_in_fragment_allowed():
    text = "Труба 20х20, толщина 2 мм."
    raw = [{"category": "quality", "level": "advice", "title": "Сухо про 20х20",
            "why": "нет пользы", "fragment": "Труба 20х20",
            "suggestions": []}]
    out = A.validate_issues(raw, text, _SETTINGS)
    assert len(out) == 1
    assert out[0]["fragment"] == "Труба 20х20"


def test_fact_and_promise_forced_to_warning_no_options():
    text = "Отгрузим быстро."
    raw = [{"category": "promise", "level": "advice", "title": "Обещание срока",
            "why": "риск", "fragment": "Отгрузим быстро",
            "suggestions": [{"when": "", "text": "Отгрузим оперативно"}]}]
    out = A.validate_issues(raw, text, _SETTINGS)
    assert out and out[0]["level"] == "warning"
    # для promise замены не показываем
    assert out[0]["options"] == []


def test_option_with_new_number_dropped():
    text = "Настил закрепили на поддонах."
    raw = [{"category": "quality", "level": "advice", "title": "Сухо",
            "why": "", "fragment": "закрепили на поддонах",
            "suggestions": [
                {"when": "", "text": "надёжно закрепили на 5 поддонах"},
                {"when": "", "text": "аккуратно закрепили на поддонах"}]}]
    out = A.validate_issues(raw, text, _SETTINGS)
    assert len(out) == 1
    # вариант с числом «5» (которого нет в тексте) отброшен, остался один
    assert [o["text"] for o in out[0]["options"]] == [
        "аккуратно закрепили на поддонах"]


def test_fragment_not_in_text_cleared():
    text = "Короткий текст."
    raw = [{"category": "tone", "level": "advice", "title": "Тон",
            "why": "", "fragment": "чего тут нет",
            "suggestions": [{"when": "", "text": "любой вариант"}]}]
    out = A.validate_issues(raw, text, _SETTINGS)
    assert len(out) == 1
    # фрагмент не найден -> обнулён, значит и вариантов замены нет (некуда ставить)
    assert out[0]["fragment"] == ""
    assert out[0]["options"] == []


def test_category_toggle_off():
    text = "Текст."
    raw = [{"category": "tone", "level": "advice", "title": "Тон", "why": "",
            "fragment": "", "suggestions": []}]
    s = dict(_SETTINGS, check_tone=False)
    assert A.validate_issues(raw, text, s) == []


def test_max_issues_limit():
    text = "Текст."
    raw = [{"category": "quality", "level": "advice", "title": "сухо",
            "why": "", "fragment": "", "suggestions": []} for _ in range(10)]
    s = dict(_SETTINGS, max_issues=3)
    assert len(A.validate_issues(raw, text, s)) == 3


def test_report_source():
    ai = Issue("СМУ", 1, "Пост", Level.ADVICE, "ai_quality", "сухо")
    rule = Issue("СМУ", 1, "Пост", Level.ERROR, "text_placeholder", "заглушка")
    assert R._issue_source(ai) == "Нейросеть"
    assert R._issue_source(rule) == "Правило"
