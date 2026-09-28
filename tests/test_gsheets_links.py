"""Извлечение ссылок из ячеек Google Sheets, включая смарт-чип (chipRuns)."""
from checker import gsheets as G


def test_smart_chip_uri():
    # A1: смарт-чип на всю ячейку (адрес в chipRuns) — без textFormatRuns
    chip_cell = {
        "userEnteredValue": {"stringValue": "Статья про швеллер"},
        "chipRuns": [{"startIndex": 0, "chip": {"richLinkProperties": {
            "uri": "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStU/edit"}}}],
    }
    assert G._cell_links(chip_cell) == [
        "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStU/edit"]


def test_hyperlink_uri():
    # A2: чипа нет, адрес в hyperlink
    hl_cell = {"userEnteredValue": {"stringValue": "Каталог"},
               "hyperlink": "https://stalmetural.ru/catalog/"}
    assert G._cell_links(hl_cell) == ["https://stalmetural.ru/catalog/"]


def test_chip_priority_over_hyperlink():
    both = {"userEnteredValue": {"stringValue": "X"},
            "chipRuns": [{"chip": {"richLinkProperties": {"uri": "https://a.ru/chip"}}}],
            "hyperlink": "https://a.ru/hl"}
    links = G._cell_links(both)
    # чип идёт первым (приоритетнее), hyperlink — следом
    assert links[0] == "https://a.ru/chip"
    assert "https://a.ru/hl" in links


def test_textformatruns_and_formula():
    cell = {
        "userEnteredValue": {"formulaValue": '=HYPERLINK("https://f.ru/doc";"Док")'},
        "textFormatRuns": [{"format": {"link": {"uri": "https://t.ru/part"}}}],
    }
    links = G._cell_links(cell)
    assert "https://f.ru/doc" in links
    assert "https://t.ru/part" in links


def test_empty_cell():
    assert G._cell_links({"userEnteredValue": {"stringValue": "просто текст"}}) == []
