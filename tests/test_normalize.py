import datetime as dt

from checker import normalize as N


def test_parse_date_text():
    assert N.parse_date("04.03.2026")[0] == dt.date(2026, 3, 4)


def test_parse_date_serial():
    # критерий приёмки: 46093 -> 12.03.2026
    assert N.parse_date(46093)[0] == dt.date(2026, 3, 12)
    assert N.parse_date("46093")[0] == dt.date(2026, 3, 12)


def test_parse_date_datetime():
    assert N.parse_date(dt.datetime(2026, 4, 12, 0, 0))[0] == dt.date(2026, 4, 12)


def test_parse_date_bad():
    d, err = N.parse_date("не дата")
    assert d is None and err


def test_parse_date_empty():
    assert N.parse_date("") == (None, None)
    assert N.parse_date(None) == (None, None)


def test_extract_links_multiple():
    cell = 'https://t.me/inmetprom/142\nhttps://ok.ru/group/700 "https://vk.com/wall-1_2"'
    links = N.extract_links(cell)
    assert len(links) == 3
    assert "https://t.me/inmetprom/142" in links


def test_normalize_link_aliases():
    assert N.normalize_link("https://m.vk.com/wall-1_2?utm_campaign=web_share") == \
        N.normalize_link("https://vk.com/wall-1_2")
    assert N.normalize_link("https://telegram.me/x/1") == "t.me/x/1"
    assert N.normalize_link("https://m.ok.ru/group/700/") == "ok.ru/group/700"


def test_private_tg_link():
    assert N.is_private_tg_link("https://t.me/c/2203619795/981")
    assert not N.is_private_tg_link("https://t.me/inmetprom/142")


def test_brand_ids_from_links():
    assert N.tg_channel_from_link("https://t.me/inmetprom/142") == "inmetprom"
    assert N.vk_group_id_from_link("https://vk.com/wall-217668235_819") == "-217668235"
    assert N.ok_group_id_from_link("https://ok.ru/group/70000004574376/topic/1") == \
        "70000004574376"


def test_phone_normalization_dashes():
    tpl = "+7 (499) 130‑36‑69"   # неразрывные дефисы U+2011
    post = "+7 (499) 130-36-69"            # обычные дефисы
    same_digits, same_literal = N.phones_equal(post, tpl)
    assert same_digits and not same_literal


def test_canonical_post_type():
    mapping = {"Информационный": ["Информативый", "Информативный"]}
    canon, literal = N.canonical_post_type("Информативый", mapping)
    assert canon == "Информационный" and literal is False
    canon, literal = N.canonical_post_type("Информационный", mapping)
    assert canon == "Информационный" and literal is True


def test_canonical_social():
    mapping = {"Одноклассники": ["Однокласники", "Однокласники "]}
    canon, literal = N.canonical_social("Однокласники ", mapping)
    assert canon == "Одноклассники" and literal is False
