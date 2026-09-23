"""Тесты чтения текста из внешних ссылок — только разбор, без сети."""
from checker import content_fetch as CF


def test_doc_id_from_document_url():
    url = "https://docs.google.com/document/d/1AbC_def-123/edit?usp=sharing"
    assert CF._doc_id(url) == "1AbC_def-123"


def test_doc_id_from_file_url():
    url = "https://drive.google.com/file/d/XyZ789/view"
    assert CF._doc_id(url) == "XyZ789"


def test_doc_id_empty():
    assert CF._doc_id("https://dzen.ru/a/abc") == ""


def test_dzen_body_from_ldjson():
    body = "А" * 250  # длиннее порога в 200 символов
    html = (
        '<html><head>'
        '<script type="application/ld+json">'
        '{"@type":"Article","headline":"Заголовок","articleBody":"' + body + '"}'
        '</script></head><body>...</body></html>')
    out = CF.dzen_body_from_html(html)
    assert out == body


def test_dzen_body_short_ignored():
    html = ('<script type="application/ld+json">'
            '{"articleBody":"слишком коротко"}</script>')
    assert CF.dzen_body_from_html(html) == ""


def test_dzen_body_no_json():
    assert CF.dzen_body_from_html("<html><body>нет разметки</body></html>") == ""


def test_dispatch_other_link():
    text, kind, err = CF.fetch_link_text("https://example.com/page", None)
    assert kind == "other"
    assert err and "поддерживается" in err


def test_dispatch_gdoc_without_sa():
    text, kind, err = CF.fetch_link_text(
        "https://docs.google.com/document/d/abc/edit", None)
    assert kind == "gdoc"
    assert err and "сервисный аккаунт" in err
