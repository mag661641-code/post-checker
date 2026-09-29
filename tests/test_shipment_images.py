"""Тесты проверки картинок отгрузок (checker/shipment_images.py). Без сети."""
from checker import shipment_images as SI
from checker.models import Level


def _levels(problems):
    return [(p.what, p.level) for p in problems]


# ---------------------------------------------------------------------------
# Валидация имён (реальные кейсы из исходного проекта)
# ---------------------------------------------------------------------------
def test_slash_is_error():
    v = SI.validate_image_name("truby-profilnye/-otgruzka-3097")
    assert v["errors"]
    assert "/" in "".join(v["errors"]) or "«/»" in "".join(v["errors"])


def test_transliteration_c_is_warning():
    v = SI.validate_image_name("truba-ocinkovannaya-otgruzka-3147")
    assert v["warnings"]
    assert not v["errors"]  # само имя валидно, только предупреждение о «ц»


def test_ch_is_not_flagged():
    v = SI.validate_image_name("plechevye-3001")
    assert not v["warnings"]


def test_uppercase_is_error():
    v = SI.validate_image_name("Truba-3001")
    assert v["errors"]


def test_strip_extension():
    assert SI.strip_extension("foto.WEBP") == "foto"
    assert SI.strip_extension("foto-3001.jpg") == "foto-3001"


def test_find_similar_catches_typo():
    hit = SI.find_similar("truba-3001", ["truba-3002", "drugoe-9999"], 3)
    assert hit and hit["name"] == "truba-3002"


# ---------------------------------------------------------------------------
# Чтение эталонов из сетки
# ---------------------------------------------------------------------------
def test_read_expected_from_grid():
    grid = [
        ["A", "B", "имя"],           # заголовок (строка 1)
        [None, None, "truba-3001"],  # строка 2
        [None, None, "  truba-3002.jpg  "],
        [None, None, ""],            # пусто — пропуск
    ]
    exp = SI.read_expected_from_grid(grid, name_col=2, first_data_row=1)
    assert [e["name"] for e in exp] == ["truba-3001", "truba-3002"]
    assert exp[0]["row"] == 2


# ---------------------------------------------------------------------------
# Сверка бренда с Диском
# ---------------------------------------------------------------------------
def _brand_cfg():
    return {"sheet": "СМУ", "require_jpg": True, "require_webp": True}


def test_missing_on_drive_is_error():
    expected = [{"name": "truba-3001", "raw": "truba-3001", "row": 2,
                 "jpg_url": "", "webp_url": ""}]
    drive = {}  # ничего нет на Диске
    res = SI.check_one_brand("СМУ", expected, drive, _brand_cfg(), 150, 3)
    whats = [p.what for p in res["problems"]]
    assert "Нет на Диске" in whats


def test_full_match_no_errors():
    expected = [{"name": "truba-3001", "raw": "truba-3001", "row": 2,
                 "jpg_url": "", "webp_url": ""}]
    drive = {"truba-3001": [
        {"name": "truba-3001.jpg", "ext": "jpg", "size_kb": 50, "url": "u1"},
        {"name": "truba-3001.webp", "ext": "webp", "size_kb": 20, "url": "u2"},
    ]}
    res = SI.check_one_brand("СМУ", expected, drive, _brand_cfg(), 150, 3)
    assert SI.count_errors({"per_brand": [res], "site": []}) == 0


def test_duplicate_name_in_registry():
    expected = [
        {"name": "truba-3001", "raw": "truba-3001", "row": 2, "jpg_url": "",
         "webp_url": ""},
        {"name": "truba-3001", "raw": "truba-3001", "row": 3, "jpg_url": "",
         "webp_url": ""},
    ]
    drive = {"truba-3001": [
        {"name": "truba-3001.jpg", "ext": "jpg", "size_kb": 50, "url": "u"},
        {"name": "truba-3001.webp", "ext": "webp", "size_kb": 20, "url": "u"},
    ]}
    res = SI.check_one_brand("СМУ", expected, drive, _brand_cfg(), 150, 3)
    assert any(p.what == "Дубль имени в реестре" for p in res["problems"])


def test_orphan_on_drive_is_warning():
    expected = [{"name": "truba-3001", "raw": "truba-3001", "row": 2,
                 "jpg_url": "", "webp_url": ""}]
    drive = {
        "truba-3001": [
            {"name": "truba-3001.jpg", "ext": "jpg", "size_kb": 50, "url": "u"},
            {"name": "truba-3001.webp", "ext": "webp", "size_kb": 20, "url": "u"}],
        "lishniy-9999": [
            {"name": "lishniy-9999.jpg", "ext": "jpg", "size_kb": 10, "url": "u"}],
    }
    res = SI.check_one_brand("СМУ", expected, drive, _brand_cfg(), 150, 3)
    assert any(p.what == "Есть на Диске, нет в реестре" for p in res["problems"])


def test_uppercase_extension_is_error():
    expected = [{"name": "truba-3001", "raw": "truba-3001", "row": 2,
                 "jpg_url": "", "webp_url": ""}]
    drive = {"truba-3001": [
        {"name": "truba-3001.JPG", "ext": "JPG", "size_kb": 50, "url": "u"},
        {"name": "truba-3001.webp", "ext": "webp", "size_kb": 20, "url": "u"}]}
    res = SI.check_one_brand("СМУ", expected, drive, _brand_cfg(), 150, 3)
    assert any("аглавн" in p.what for p in res["problems"])


def test_heavy_file_is_warning():
    expected = [{"name": "truba-3001", "raw": "truba-3001", "row": 2,
                 "jpg_url": "", "webp_url": ""}]
    drive = {"truba-3001": [
        {"name": "truba-3001.jpg", "ext": "jpg", "size_kb": 500, "url": "u"},
        {"name": "truba-3001.webp", "ext": "webp", "size_kb": 20, "url": "u"}]}
    res = SI.check_one_brand("СМУ", expected, drive, _brand_cfg(), 150, 3)
    assert any(p.what == "Тяжёлый файл" for p in res["problems"])


# ---------------------------------------------------------------------------
# Разбор ответа сайта
# ---------------------------------------------------------------------------
def test_site_404():
    p = SI.evaluate_site_response(404, {}, "http://x/i.jpg", "СМУ", "i", 2)
    assert p and p.level == Level.ERROR


def test_site_ok_image_none():
    p = SI.evaluate_site_response(200, {"Content-Type": "image/jpeg"},
                                  "http://x/i.jpg", "СМУ", "i", 2)
    assert p is None


def test_site_ok_but_not_image():
    p = SI.evaluate_site_response(200, {"Content-Type": "text/html"},
                                  "http://x/i.jpg", "СМУ", "i", 2)
    assert p and p.level == Level.ERROR
