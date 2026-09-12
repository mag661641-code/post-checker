"""Проверки контактов по типам постов, анкор-ссылки, сноска, тире, фото."""
from checker import text_checks as T
from checker.models import Level, PostRecord


def _post(text, brand="СМУ", ptype="Отгрузка", photos=None, socials=None,
          text_links=None, row=1):
    return PostRecord(sheet=brand, row=row, brand=brand, post_type=ptype,
                      text=text, photos=photos or [], socials=socials or [],
                      text_links=text_links or [])


def _codes(post, code, brands, rules):
    return [i.code for i in T.check_contacts_present(post, code, brands, rules)]


# --- анкор-ссылка на сайт в информационном посте (кейс МПЭ) ---
def test_info_anchor_with_link_no_error(brands, rules):
    p = _post("...оформить заказ можно на нашем сайте", brand="МПЭ",
              ptype="Информационный", text_links=["https://mepen.ru/catalog/"])
    codes = _codes(p, "МПЭ", brands, rules)
    assert "text_no_site" not in codes
    assert "text_no_phone" not in codes
    assert "text_site_anchor_no_link" not in codes


def test_info_anchor_without_link_warns(brands, rules):
    p = _post("...оформить заказ можно на нашем сайте", brand="МПЭ",
              ptype="Информационный", text_links=[])
    codes = _codes(p, "МПЭ", brands, rules)
    assert "text_site_anchor_no_link" in codes
    assert "text_no_phone" not in codes


def test_info_no_anchor_no_link_error(brands, rules):
    p = _post("Просто информационный текст без ссылки и слов-анкоров.",
              brand="МПЭ", ptype="Информационный")
    codes = _codes(p, "МПЭ", brands, rules)
    assert "text_no_site" in codes


# --- праздник: контактов быть не должно ---
def test_holiday_no_contacts(brands, rules):
    p = _post("С праздником!", brand="ИМП", ptype="Праздник")
    assert T.check_contacts_present(p, "ИМП", brands, rules) == []


# --- отгрузка без телефона: ошибка про телефон остаётся ---
def test_shipment_missing_phone(brands, rules):
    p = _post("Отгрузили металл. stalmetural.ru info@stalmetural.ru",
              brand="СМУ", ptype="Отгрузка")
    assert "text_no_phone" in _codes(p, "СМУ", brands, rules)


# --- снять галочку «Сайт» у типа: замечание про сайт исчезает ---
def test_site_toggle_off_via_brand_override(brands, rules):
    b = dict(brands)
    b["СМУ"] = dict(brands["СМУ"], type_rules={"Информационный": {"site": False}})
    p = _post("Инфопост без сайта", brand="СМУ", ptype="Информационный")
    codes = _codes(p, "СМУ", b, rules)
    assert "text_no_site" not in codes
    assert "text_site_anchor_no_link" not in codes


# --- нераспознанный тип: 🟡 и пропуск ---
def test_unknown_type_skips(brands, rules):
    p = _post("Текст", brand="СМУ", ptype="Абракадабра")
    issues = T.check_contacts_present(p, "СМУ", brands, rules)
    assert len(issues) == 1 and issues[0].code == "text_type_unknown"
    assert issues[0].level == Level.WARNING


# --- МПИ спецпредложение: телефон/почта не нужны, сайт через анкор ---
def test_mpi_spec_no_phone_email(brands, rules):
    p = _post("Скидка на металл. на нашем сайте", brand="МПИ",
              ptype="Спецпредложение", text_links=["https://metpromintex.ru/x"])
    codes = _codes(p, "МПИ", brands, rules)
    assert "text_no_phone" not in codes and "text_no_email" not in codes


# --- сноска в спецпредложении ---
def test_footnote_missing(brands, rules):
    p = _post("Цена 100 руб. #тег", brand="СМУ", ptype="Спецпредложение")
    codes = [i.code for i in T.check_offer_footnote(p, "СМУ", brands, rules)]
    assert "text_offer_footnote" in codes


def test_footnote_present(brands, rules):
    fn = brands["СМУ"]["offer_footnote"]
    p = _post(f"Спецпредложение по цене.\n{fn}\n#тег", brand="СМУ",
              ptype="Спецпредложение")
    assert T.check_offer_footnote(p, "СМУ", brands, rules) == []


# --- короткое тире ---
def test_short_dash(brands, rules):
    p = _post("сталь – ежедневно")
    codes = [i.code for i in T.check_short_dash(p, "СМУ", brands, rules)]
    assert "text_short_dash" in codes


# --- фото отгрузки: нужны обе строки ---
def test_shipment_labels_missing(brands, rules):
    p = _post("Отгрузка", ptype="Отгрузка",
              photos=["ЛОГО: https://i.ibb.co/x/1.jpg"])
    codes = [i.code for i in T.check_shipment_photo_labels(p, "СМУ", brands, rules)]
    assert "text_shipment_labels" in codes


def test_shipment_labels_ok(brands, rules):
    p = _post("Отгрузка", ptype="Отгрузка",
              photos=["ЛОГО: https://i.ibb.co/x/1.jpg",
                      "БЕЗ ЛОГО: https://i.ibb.co/y/2.jpg"])
    assert T.check_shipment_photo_labels(p, "СМУ", brands, rules) == []
