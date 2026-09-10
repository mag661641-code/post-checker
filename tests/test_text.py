from checker import text_checks as T
from checker.models import Level, PostRecord


def _post(text, brand="СМУ", ptype="Отгрузка", photos=None, row=1):
    return PostRecord(sheet=brand, row=row, brand=brand, post_type=ptype,
                      text=text, photos=photos or [])


def test_placeholder(brands, rules):
    p = _post("Отгрузили металл в [Город] для [Отрасль].")
    issues = T.check_placeholders(p, "СМУ", brands, rules)
    assert len(issues) >= 1 and all(i.level == Level.ERROR for i in issues)


def test_prompt_leftover(brands, rules):
    p = _post("Далее пример поста. Отгрузили трубы.")
    issues = T.check_prompt_leftovers(p, "СМУ", brands, rules)
    assert issues and issues[0].level == Level.ERROR


def test_doubled_letter(brands, rules):
    p = _post("Наш завод Рработает без выходных.", brand="АПС", row=167)
    issues = T.check_doubled_letter(p, "АПС", brands, rules)
    assert issues and "работает" in issues[0].message.lower()


def test_doubled_word(brands, rules):
    p = _post("Это очень очень качественный металл.")
    issues = T.check_doubled_word(p, "СМУ", brands, rules)
    assert issues and issues[0].level == Level.WARNING


def test_weird_hashtag(brands, rules):
    p = _post("Отгрузка #ДвутаврСтальной1 готова.")
    issues = T.check_weird_hashtag(p, "СМУ", brands, rules)
    assert issues and issues[0].level == Level.WARNING


def test_other_brand_name(brands, rules):
    p = _post("Компания Инметпром отгрузила металл.", brand="СМУ")
    issues = T.check_other_brand_name(p, "СМУ", brands, rules)
    assert any(i.code == "text_other_name" for i in issues)


def test_missing_hashtags(brands, rules):
    p = _post("Отгрузили металл. #СМУ", brand="СМУ", ptype="Отгрузка")
    issues = T.check_required_hashtags(p, "СМУ", brands, rules)
    assert issues and issues[0].level == Level.WARNING


def test_mpi_first_hashtag(brands, rules):
    p = _post("Пост #МПИ #МетПромИнтекс", brand="МПИ", ptype="Отгрузка")
    issues = T.check_mpi_first_hashtag(p, "МПИ", brands, rules)
    assert issues and issues[0].code == "text_mpi_first"


def test_colon_in_list_mpe(brands, rules):
    p = _post("Преимущества:\n• прочность: высокая\n• цена низкая", brand="МПЭ")
    issues = T.check_colon_in_list(p, "МПЭ", brands, rules)
    assert issues and issues[0].level == Level.WARNING


def test_telegram_caption_length(brands, rules):
    long = "а" * 1100
    p = _post(long, photos=["https://i.ibb.co/x/1.jpg"])
    issues = T.check_telegram_length(p, "СМУ", brands, rules)
    assert issues and issues[0].code == "text_tg_caption"


def test_photo_filename(brands, rules):
    p = _post("Пост", photos=["ЛОГО: РЖАВЧИНА НА МЕТАЛЛЕ.jpg"])
    issues = T.check_photo_filename(p, "СМУ", brands, rules)
    assert issues and issues[0].code == "text_photo_name"


def test_contacts_present_ok(brands, rules):
    text = "Пост\nstalmetural.ru\n+7 (499) 130-36-69"
    p = _post(text, brand="СМУ", ptype="Отгрузка")
    issues = T.check_contacts_present(p, "СМУ", brands, rules)
    # сайт и телефон на месте — ошибок про их отсутствие нет
    assert not any(i.code in ("text_no_site", "text_no_phone") for i in issues)


def test_type_spelling_text(brands, rules):
    p = _post("текст", ptype="Информативый")
    issues = T.check_post_type_spelling(p, "СМУ", brands, rules)
    assert issues and issues[0].code == "text_type_spelling"
