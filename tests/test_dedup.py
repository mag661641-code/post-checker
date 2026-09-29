"""Тесты проверки дублей идей (checker/dedup.py). Без сети и без Streamlit."""
from checker import dedup
from checker.dedup import Idea, Thresholds


def _prep(row, text, published=""):
    return Idea(row=row, raw=text, published=published).prepare(400)


# ---------------------------------------------------------------------------
# Обработка текста
# ---------------------------------------------------------------------------
def test_normalize_lowercases_and_ye():
    assert dedup.normalize("Ёлка, ПРОКАТ!") == "елка прокат"


def test_stem_set_drops_stopwords_and_short():
    stems = dedup.stem_set("как правильно хранить металлопрокат")
    # «как» — стоп-слово, остальные — значимые основы
    assert "как" not in stems
    assert any(s.startswith("хран") for s in stems)
    assert any(s.startswith("металлопрок") for s in stems)


def test_levenshtein_ratio_identical():
    assert dedup.levenshtein_ratio("abc", "abc") == 1.0


# ---------------------------------------------------------------------------
# Лексическая похожесть
# ---------------------------------------------------------------------------
def test_identical_is_one():
    a = _prep(2, "как хранить металлопрокат")
    b = _prep(3, "как хранить металлопрокат")
    assert dedup.lexical_similarity(a.norm, a.stems, b.norm, b.stems) == 1.0


def test_paraphrase_is_similar_not_zero():
    a = _prep(2, "как правильно хранить металлопрокат")
    b = _prep(3, "как транспортировать и хранить металлопрокат зимой")
    sim = dedup.lexical_similarity(a.norm, a.stems, b.norm, b.stems)
    assert sim >= Thresholds().sim_limit  # попадает хотя бы в «похоже»


def test_different_topics_low():
    a = _prep(2, "как хранить металлопрокат")
    b = _prep(3, "поздравление с днём народного единства")
    sim = dedup.lexical_similarity(a.norm, a.stems, b.norm, b.stems)
    assert sim < Thresholds().sim_limit


# ---------------------------------------------------------------------------
# Вердикты
# ---------------------------------------------------------------------------
def test_verdict_free_when_unique():
    ideas = [_prep(2, "калитка из профильной трубы"),
             _prep(3, "поздравление с новым годом")]
    verdicts = dedup.run_dedup(ideas)
    assert all(v.status == "free" for v in verdicts)


def test_verdict_taken_when_duplicate_published():
    ideas = [
        _prep(2, "как хранить металлопрокат"),
        _prep(3, "как хранить металлопрокат", published="сентябрь"),
    ]
    verdicts = {v.row: v for v in dedup.run_dedup(ideas)}
    # у первой идеи дубль (строка 3) опубликован → ЗАНЯТО
    assert verdicts[2].status == "taken"
    assert "сентябрь" in verdicts[2].message


def test_verdict_planned_when_duplicate_not_published():
    ideas = [
        _prep(2, "как хранить металлопрокат"),
        _prep(3, "как хранить металлопрокат"),
    ]
    verdicts = dedup.run_dedup(ideas)
    assert all(v.status == "planned" for v in verdicts)


def test_long_text_skipped():
    long_text = "слово " * 200  # > 400 символов
    ideas = [_prep(2, long_text)]
    verdicts = dedup.run_dedup(ideas, Thresholds())
    assert verdicts[0].status == "skipped"


# ---------------------------------------------------------------------------
# Чтение из сетки
# ---------------------------------------------------------------------------
def test_read_ideas_from_grid():
    grid = [
        ["№", "Дата", "Идея", None, None, None, None, None, None, None, "Выложено"],
        [1, None, "как хранить металлопрокат", None, None, None, None, None,
         None, None, "сентябрь"],
        [2, None, "", None, None, None, None, None, None, None, ""],  # пусто
        [3, None, "калитка из профтрубы", None, None, None, None, None, None,
         None, ""],
    ]
    ideas = dedup.read_ideas_from_grid(grid, col_idea=2, col_published=10,
                                       row_start=1)
    assert [i.row for i in ideas] == [2, 4]  # пустая строка 3 пропущена
    assert ideas[0].published == "сентябрь"


# ---------------------------------------------------------------------------
# Косинус
# ---------------------------------------------------------------------------
def test_cosine_bounds():
    assert dedup.cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert dedup.cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert dedup.cosine(None, [1.0]) == 0.0
