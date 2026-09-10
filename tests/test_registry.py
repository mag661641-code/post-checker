import datetime as dt

from checker import registry_checks as R
from checker.models import Level, RegistryRow
from checker import normalize as N


def _mk(row, brand="ИМП", status="Выложено", ptype="Отгрузка", links=None,
        write=None, pub=None, executor="Иван"):
    links = links or []
    rr = RegistryRow(row=row, brand=brand, status=status, post_type=ptype,
                     executor=executor, links=links,
                     links_norm=[N.normalize_link(u) for u in links],
                     write_date=write, pub_date=pub)
    return rr


def test_duplicate_across_rows(brands, rules):
    rows = [
        _mk(12, links=["https://t.me/inmetprom/142"]),
        _mk(16, links=["https://t.me/inmetprom/142"]),
    ]
    issues = R.check_duplicate_links(rows, brands, rules)
    across = [i for i in issues if i.code == "reg_dup_across"]
    assert {i.row for i in across} == {12, 16}
    assert all(i.level == Level.ERROR for i in across)


def test_duplicate_in_cell(brands, rules):
    rows = [_mk(27, brand="СМУ", ptype="Праздник",
                links=["https://vk.com/wall-217668235_819",
                       "https://vk.com/wall-217668235_819"])]
    issues = R.check_duplicate_links(rows, brands, rules)
    assert any(i.code == "reg_dup_in_cell" and i.level == Level.ADVICE
               for i in issues)


def test_private_link_ready_ok(brands, rules):
    rows = [_mk(5, status="Готово", links=["https://t.me/c/2203619795/981"])]
    assert R.check_posted_private_link(rows, brands, rules) == []


def test_private_link_posted_error(brands, rules):
    rows = [_mk(5, status="Выложено", links=["https://t.me/c/2203619795/981"])]
    issues = R.check_posted_private_link(rows, brands, rules)
    assert len(issues) == 1 and issues[0].level == Level.ERROR


def test_wrong_brand_link(brands, rules):
    # ссылка ИМП в строке СМУ
    rows = [_mk(3, brand="СМУ", links=["https://t.me/inmetprom/142"])]
    issues = R.check_wrong_brand_link(rows, brands, rules)
    assert any(i.code == "reg_wrong_brand_link" for i in issues)


def test_ready_past(brands, rules):
    rows = [_mk(9, status="Готово", pub=dt.date(2020, 1, 1))]
    issues = R.check_ready_past(rows, brands, rules, today=dt.date(2026, 1, 1))
    assert issues and issues[0].code == "reg_ready_past"


def test_posted_future(brands, rules):
    rows = [_mk(9, status="Выложено", pub=dt.date(2030, 1, 1))]
    issues = R.check_posted_future(rows, brands, rules, today=dt.date(2026, 1, 1))
    assert issues and issues[0].code == "reg_posted_future"


def test_type_spelling(brands, rules):
    rows = [_mk(71, ptype="Информативый")]
    issues = R.check_post_type_spelling(rows, brands, rules)
    assert issues and issues[0].level == Level.WARNING


def test_empty_executor(brands, rules):
    rows = [_mk(5, executor="-", links=["https://t.me/inmetprom/1"])]
    issues = R.check_empty_fields(rows, brands, rules)
    assert any(i.code == "reg_no_executor" for i in issues)
