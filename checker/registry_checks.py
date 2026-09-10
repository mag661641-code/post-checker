"""Проверки главного реестра «Реестр постов».

Каждая проверка — отдельная функция, включается/выключается через rules['toggles'].
Все функции принимают (rows, brands, rules) и возвращают list[Issue].
"""
from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any

from . import normalize as N
from .models import Issue, Level, RegistryRow

SHEET = "Реестр постов"


def check_empty_fields(rows: list[RegistryRow], brands, rules) -> list[Issue]:
    issues = []
    for r in rows:
        missing = []
        if not r.brand:
            missing.append("бренд")
        if not r.post_type:
            missing.append("тип поста")
        if not r.status:
            missing.append("статус")
        if not r.links:
            missing.append("ссылка")
        if missing:
            issues.append(Issue(
                SHEET, r.row, "Бренд/Тип/Статус/Ссылка", Level.WARNING,
                "reg_empty",
                f"Не заполнены обязательные поля: {', '.join(missing)}.",
                "Заполните пустые ячейки, иначе пост нельзя однозначно проверить.",
                brand=r.brand, status=r.status, post_type=r.post_type,
            ))
        if not r.executor or r.executor == "-":
            issues.append(Issue(
                SHEET, r.row, "Исполнитель", Level.WARNING, "reg_no_executor",
                "Не указан исполнитель (пусто или «-»).",
                "Впишите ответственного, чтобы было видно, кто готовил пост.",
                brand=r.brand, status=r.status, post_type=r.post_type,
            ))
    return issues


def check_bad_date(rows: list[RegistryRow], brands, rules) -> list[Issue]:
    issues = []
    for r in rows:
        for raw, col, label in [(r.write_date_raw, "Дата написания", "написания"),
                                (r.pub_date_raw, "Дата публикации (План)", "публикации")]:
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                continue
            d, err = N.parse_date(raw)
            if d is None and err:
                issues.append(Issue(
                    SHEET, r.row, col, Level.ERROR, "reg_bad_date",
                    f"Дата {label} не распознана: {raw!r}.",
                    "Запишите дату в формате ДД.ММ.ГГГГ (например, 12.04.2026).",
                    brand=r.brand, status=r.status, post_type=r.post_type,
                ))
    return issues


def check_pub_before_write(rows: list[RegistryRow], brands, rules) -> list[Issue]:
    issues = []
    for r in rows:
        if r.write_date and r.pub_date and r.pub_date < r.write_date:
            issues.append(Issue(
                SHEET, r.row, "Дата публикации (План)", Level.WARNING,
                "reg_pub_before_write",
                f"Дата публикации ({r.pub_date:%d.%m.%Y}) раньше даты написания "
                f"({r.write_date:%d.%m.%Y}).",
                "Проверьте даты: пост не может быть опубликован до того, как написан.",
                brand=r.brand, status=r.status, post_type=r.post_type,
            ))
    return issues


def check_posted_future(rows: list[RegistryRow], brands, rules,
                        today: dt.date | None = None) -> list[Issue]:
    today = today or dt.date.today()
    issues = []
    for r in rows:
        if r.status == "Выложено" and r.pub_date and r.pub_date > today:
            issues.append(Issue(
                SHEET, r.row, "Статус", Level.WARNING, "reg_posted_future",
                f"Статус «Выложено», но дата публикации в будущем "
                f"({r.pub_date:%d.%m.%Y}).",
                "Уточните: пост ещё не должен быть опубликован — возможно, неверна дата или статус.",
                brand=r.brand, status=r.status, post_type=r.post_type,
            ))
    return issues


def check_ready_past(rows: list[RegistryRow], brands, rules,
                     today: dt.date | None = None) -> list[Issue]:
    today = today or dt.date.today()
    issues = []
    for r in rows:
        if r.status == "Готово" and r.pub_date and r.pub_date < today:
            issues.append(Issue(
                SHEET, r.row, "Статус", Level.WARNING, "reg_ready_past",
                f"Статус «Готово», а дата публикации уже прошла "
                f"({r.pub_date:%d.%m.%Y}).",
                "Возможно, пост забыли выложить или не обновили статус на «Выложено».",
                brand=r.brand, status=r.status, post_type=r.post_type,
            ))
    return issues


def check_posted_private_link(rows: list[RegistryRow], brands, rules) -> list[Issue]:
    issues = []
    for r in rows:
        if r.status != "Выложено":
            continue
        for url in r.links:
            if N.is_private_tg_link(url):
                issues.append(Issue(
                    SHEET, r.row, "Ссылка", Level.ERROR, "reg_private_link",
                    "Статус «Выложено», но ссылка ведёт в закрытый рабочий чат "
                    f"(t.me/c/...): {url}",
                    "Пост не опубликован или вставлена черновая ссылка. "
                    "Замените на ссылку на опубликованный пост.",
                    brand=r.brand, status=r.status, post_type=r.post_type, link=url,
                ))
    return issues


def check_duplicate_links(rows: list[RegistryRow], brands, rules) -> list[Issue]:
    issues = []
    # дубли внутри одной ячейки -> совет
    for r in rows:
        seen: dict[str, int] = defaultdict(int)
        for norm in r.links_norm:
            if not N.is_private_tg_link(norm):
                seen[norm] += 1
        for norm, cnt in seen.items():
            if cnt > 1:
                issues.append(Issue(
                    SHEET, r.row, "Ссылка", Level.ADVICE, "reg_dup_in_cell",
                    f"Одна и та же ссылка указана {cnt} раза в одной ячейке ({norm}).",
                    "Уберите повтор ссылки.",
                    brand=r.brand, status=r.status, post_type=r.post_type, link=norm,
                ))
    # дубли между строками -> ошибка
    positions: dict[str, list[int]] = defaultdict(list)
    for r in rows:
        for norm in set(r.links_norm):
            if norm and not N.is_private_tg_link(norm):
                positions[norm].append(r.row)
    for norm, rws in positions.items():
        if len(rws) > 1:
            for rw in rws:
                others = [str(x) for x in rws if x != rw]
                issues.append(Issue(
                    SHEET, rw, "Ссылка", Level.ERROR, "reg_dup_across",
                    f"Эта ссылка ({norm}) встречается также в строках: "
                    f"{', '.join(others)}.",
                    "Публикация может быть учтена дважды или скопирована не та ссылка. "
                    "Проверьте все указанные строки.",
                    link=norm,
                ))
    return issues


def _brand_of_link(url: str, brands: dict) -> set[str]:
    """Каким брендам может принадлежать ссылка (по каналу/id)."""
    owners: set[str] = set()
    tg = N.tg_channel_from_link(url)
    vk = N.vk_group_id_from_link(url)
    ok = N.ok_group_id_from_link(url)
    mx = N.max_channel_id_from_link(url)
    for code, b in brands.items():
        tgs = set()
        tgmap = b.get("telegram", {})
        if isinstance(tgmap, dict):
            tgs = {str(v).lower() for v in tgmap.values() if v}
        if tg and tg in tgs:
            owners.add(code)
        if vk and str(b.get("vk_group_id", "")) == vk:
            owners.add(code)
        if ok and str(b.get("ok_group_id", "")) == ok:
            owners.add(code)
        if mx and str(b.get("max_channel_id", "")) == mx:
            owners.add(code)
    return owners


def check_wrong_brand_link(rows: list[RegistryRow], brands, rules) -> list[Issue]:
    issues = []
    for r in rows:
        if not r.brand or r.brand not in brands:
            continue
        for url in r.links:
            owners = _brand_of_link(url, brands)
            if owners and r.brand not in owners:
                issues.append(Issue(
                    SHEET, r.row, "Ссылка", Level.ERROR, "reg_wrong_brand_link",
                    f"Ссылка ведёт на канал/группу бренда "
                    f"{', '.join(sorted(owners))}, а строка помечена как {r.brand}: {url}",
                    "Проверьте бренд строки или ссылку — вероятно, скопирована ссылка "
                    "другого бренда.",
                    brand=r.brand, status=r.status, post_type=r.post_type, link=url,
                ))
    return issues


def _platform_of_link(url: str) -> str | None:
    d = N.link_domain(url)
    if d == "t.me":
        return "Telegram (сотрудники)" if N.tg_channel_from_link(url) in {"smudaily"} else "Telegram"
    if d == "ok.ru":
        return "Одноклассники"
    if d == "vk.com":
        return "ВКонтакте"
    if d == "max.ru":
        return "Max"
    if d == "dzen.ru":
        return "Дзен"
    return None


def check_missing_platforms(rows: list[RegistryRow], brands, rules) -> list[Issue]:
    issues = []
    cfg = rules.get("expected_platforms", {})
    default = cfg.get("default", [])
    by_bt = cfg.get("by_brand_type", {})
    for r in rows:
        if r.status != "Выложено":
            continue
        key = f"{r.brand}|{r.post_type}"
        star = f"*|{r.post_type}"
        expected = by_bt.get(key) or by_bt.get(star) or default
        if not expected:
            continue
        present = set()
        for url in r.links:
            p = _platform_of_link(url)
            if p == "Telegram (сотрудники)":
                present.add("Telegram (сотрудники)")
                present.add("Telegram")
            elif p:
                present.add(p)
        missing = [p for p in expected if p not in present]
        if missing:
            issues.append(Issue(
                SHEET, r.row, "Ссылка", Level.WARNING, "reg_missing_platforms",
                f"Для «Выложено» ожидались площадки: {', '.join(expected)}. "
                f"Не хватает: {', '.join(missing)}.",
                "Добавьте недостающие ссылки или уточните ожидаемые площадки в настройках.",
                brand=r.brand, status=r.status, post_type=r.post_type,
            ))
    return issues


def check_unknown_domain(rows: list[RegistryRow], brands, rules) -> list[Issue]:
    known = set(rules.get("known_domains", []))
    issues = []
    for r in rows:
        for url in r.links:
            d = N.link_domain(url)
            if d and d not in known:
                issues.append(Issue(
                    SHEET, r.row, "Ссылка", Level.WARNING, "reg_unknown_domain",
                    f"Неизвестный домен в ссылке: {d} ({url}).",
                    "Проверьте ссылку. Если домен верный, добавьте его в список "
                    "известных доменов в настройках.",
                    brand=r.brand, status=r.status, post_type=r.post_type, link=url,
                ))
    return issues


def check_post_type_spelling(rows: list[RegistryRow], brands, rules) -> list[Issue]:
    mapping = rules.get("post_type_canonical", {})
    issues = []
    for r in rows:
        if not r.post_type:
            continue
        canon, literal = N.canonical_post_type(r.post_type, mapping)
        if not literal and canon:
            issues.append(Issue(
                SHEET, r.row, "Тип поста", Level.WARNING, "reg_type_spelling",
                f"Тип поста записан как «{r.post_type}», эталон — «{canon}».",
                f"Приведите написание к «{canon}» для единообразия.",
                brand=r.brand, status=r.status, post_type=r.post_type,
            ))
    return issues


# --- реестр проверок с ключами переключателей ---
REGISTRY_CHECKS = [
    ("registry_empty_fields", check_empty_fields),
    ("registry_bad_date", check_bad_date),
    ("registry_pub_before_write", check_pub_before_write),
    ("registry_posted_future", check_posted_future),
    ("registry_ready_past", check_ready_past),
    ("registry_posted_private_link", check_posted_private_link),
    ("registry_duplicate_links", check_duplicate_links),
    ("registry_wrong_brand_link", check_wrong_brand_link),
    ("registry_missing_platforms", check_missing_platforms),
    ("registry_unknown_domain", check_unknown_domain),
    ("registry_post_type_spelling", check_post_type_spelling),
]


def run_registry_checks(rows: list[RegistryRow], brands: dict, rules: dict) -> list[Issue]:
    toggles = rules.get("toggles", {})
    issues: list[Issue] = []
    for key, fn in REGISTRY_CHECKS:
        if not toggles.get(key, True):
            continue
        try:
            issues.extend(fn(rows, brands, rules))
        except Exception as e:  # noqa: BLE001
            issues.append(Issue(
                SHEET, None, "", Level.TECH, f"tech_{key}",
                f"Проверка «{key}» не сработала: {e}",
                "Остальные проверки выполнены. Сообщите разработчику код проверки.",
            ))
    return issues
