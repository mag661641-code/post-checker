"""Проверки текстов постов (листы брендов).

Каждая проверка — функция (post, brand_code, brands, rules) -> list[Issue].
Проверки орфографии вынесены в отдельную функцию (нужен интернет).
"""
from __future__ import annotations

import re
from typing import Any

from . import normalize as N
from .models import Issue, Level, PostRecord


# ---------------------------------------------------------------------------
# Вспомогательное
# ---------------------------------------------------------------------------
def _hashtags(text: str) -> list[str]:
    return re.findall(r"#[\wА-Яа-яЁё]+", text)


def _lines(text: str) -> list[str]:
    return text.split("\n")


def _brand_by_site_or_phone(text: str, brands: dict) -> set[str]:
    """Найти бренды, чьи контакты (сайт/телефон/e-mail) встречаются в тексте."""
    found: set[str] = set()
    digits = re.sub(r"\D", " ", text)
    for code, b in brands.items():
        site = str(b.get("site", "")).lower()
        email = str(b.get("email", "")).lower()
        phone = N.normalize_phone(b.get("phone", ""))
        low = text.lower()
        if site and site in low:
            found.add(code)
        if email and email in low:
            found.add(code)
        if phone and len(phone) >= 7 and phone in re.sub(r"\D", "", text):
            found.add(code)
    return found


# ---------------------------------------------------------------------------
# Контакты и бренд
# ---------------------------------------------------------------------------
def _is_staff_channel_post(post: PostRecord, b: dict) -> bool:
    """Пост опубликован только в канале для сотрудников (напр. t.me/SMUdaily).

    Учитываем лишь бренды, у которых канал сотрудников отличается от
    клиентского, — иначе (когда оба поля совпадают) отдельного «служебного»
    канала нет и контакты проверять нужно.
    """
    tg = b.get("telegram", {})
    if not isinstance(tg, dict):
        return False
    staff = (tg.get("staff") or "").lower()
    clients = (tg.get("clients") or "").lower()
    if not staff or staff == clients:
        return False
    for s in post.socials:
        ch = N.tg_channel_from_link(s.get("link", ""))
        if ch and ch == staff:
            return True
    return False


def type_rules_for(code: str, canon_type: str, brands: dict, rules: dict) -> dict:
    """Итоговые правила «что проверять» для бренда и типа поста.

    База — общие значения из rules['post_type_rules'], поверх — исключения
    бренда из brands[code]['type_rules']. Ключи: phone, site, email, hashtags.
    """
    base = rules.get("post_type_rules", {}).get(canon_type, {})
    out = {k: bool(base.get(k, False))
           for k in ("phone", "site", "email", "hashtags")}
    override = (brands.get(code, {}).get("type_rules", {}) or {}).get(canon_type, {})
    for k in ("phone", "site", "email", "hashtags"):
        if k in override:
            out[k] = bool(override[k])
    return out


def _site_status(post: PostRecord, site: str, rules: dict) -> str:
    """Есть ли в посте сайт бренда: ok | anchor_no_link | missing.

    Сайт засчитывается, если домен встречается в тексте, либо в ячейке есть
    гиперссылка (анкор) на домен бренда.
    """
    dom = str(site or "").lower().strip()
    if not dom:
        return "ok"
    low = (post.text or "").lower()
    if dom in low:
        return "ok"
    for u in (post.text_links or []):
        if dom in N.link_domain(u) or dom in (u or "").lower():
            return "ok"
    anchor = any(w in low for w in rules.get("anchor_words", []))
    return "anchor_no_link" if anchor else "missing"


def check_contacts_present(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    b = brands.get(code, {})
    if not b:
        return []
    # в канале для сотрудников контакты бренда не проверяются никогда
    if _is_staff_channel_post(post, b):
        return []
    # тип поста не заполнен — молча пропускаем (это ловит другая проверка)
    if not (post.post_type or "").strip():
        return []
    canon_type, _ = N.canonical_post_type(post.post_type,
                                           rules.get("post_type_canonical", {}))
    if canon_type not in rules.get("post_type_rules", {}):
        return [Issue(
            post.sheet, post.row, "Тип", Level.WARNING, "text_type_unknown",
            f"Тип поста «{post.post_type}» не распознан, проверка контактов "
            f"пропущена.",
            "Проверьте написание типа или добавьте его в настройках "
            "(«Типы постов»).",
            brand=code, post_type=post.post_type,
        )]

    need = type_rules_for(code, canon_type, brands, rules)
    issues: list[Issue] = []
    text = post.text
    low = text.lower()
    phone = N.normalize_phone(b.get("phone", ""))
    text_digits = re.sub(r"\D", "", text)

    # телефон
    if need["phone"] and phone:
        if phone not in text_digits:
            issues.append(Issue(
                post.sheet, post.row, "Пост", Level.ERROR, "text_no_phone",
                f"В тексте нет телефона бренда ({b.get('phone')}).",
                "Добавьте телефон в контактный блок.",
                brand=code, post_type=post.post_type,
            ))
        else:
            same_digits, same_literal = _phone_style(text, b.get("phone", ""))
            if same_digits and not same_literal:
                issues.append(Issue(
                    post.sheet, post.row, "Пост", Level.ADVICE, "text_phone_dash",
                    "Телефон записан другим видом дефиса, чем в шаблоне.",
                    "Не ошибка. При желании приведите дефисы к единому виду.",
                    brand=code, post_type=post.post_type,
                ))

    # e-mail
    if need["email"]:
        email = str(b.get("email", "")).lower().strip()
        if email and email not in low:
            issues.append(Issue(
                post.sheet, post.row, "Пост", Level.ERROR, "text_no_email",
                f"В тексте нет e-mail бренда ({b.get('email')}).",
                "Добавьте e-mail в контактный блок.",
                brand=code, post_type=post.post_type,
            ))

    # сайт (с учётом ссылки-анкора)
    if need["site"]:
        issues.extend(_check_site(post, code, b, need["phone"], rules))
    return issues


def _check_site(post: PostRecord, code: str, b: dict, need_phone: bool,
                rules: dict) -> list[Issue]:
    site = str(b.get("site", "")).lower()
    if not site:
        return []
    status = _site_status(post, site, rules)
    if status == "ok":
        return []
    if status == "anchor_no_link":
        return [Issue(
            post.sheet, post.row, "Пост", Level.WARNING, "text_site_anchor_no_link",
            "Похоже, ссылка на сайт должна быть в словах «на нашем сайте», "
            "но самой ссылки в ячейке нет. Проверьте, что текст действительно "
            "оформлен ссылкой.",
            "Оформите слова-анкор ссылкой на сайт (при копировании из нейросети "
            "ссылка часто отваливается).",
            brand=code, post_type=post.post_type,
        )]
    # missing
    if need_phone:
        fix = ("Добавьте сайт в контактный блок — для отгрузок и спецпредложений "
               "он обязателен.")
    else:
        fix = ("В информационном посте в конце нужна ссылка на сайт или товар, "
               "по возможности анкором.")
    return [Issue(
        post.sheet, post.row, "Пост", Level.ERROR, "text_no_site",
        f"Нет ссылки на сайт {b.get('site')}.", fix,
        brand=code, post_type=post.post_type,
    )]


def _phone_style(text: str, template_phone: str):
    """Найти в тексте телефон бренда и сравнить его запись с шаблоном."""
    tdig = N.normalize_phone(template_phone)
    for m in re.finditer(r"[+\d][\d\s()\-‐‑‒–—−  ]{9,}", text):
        cand = m.group(0)
        sd, sl = N.phones_equal(cand, template_phone)
        if sd:
            return sd, sl
    return False, False


def check_other_brand_contacts(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    others = _brand_by_site_or_phone(post.text, brands) - {code}
    issues = []
    for other in sorted(others):
        ob = brands[other]
        issues.append(Issue(
            post.sheet, post.row, "Пост", Level.ERROR, "text_other_contacts",
            f"В тексте найдены контакты другого бренда — {other} "
            f"({ob.get('site') or ob.get('phone')}).",
            "Частая ошибка при копировании шаблона. Замените на контакты своего бренда.",
            brand=code, post_type=post.post_type,
        ))
    return issues


def check_other_brand_name(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    issues = []
    low = post.text.lower()
    for other, ob in brands.items():
        if other == code:
            continue
        names = [ob.get("name", "")] + ob.get("aliases", [])
        for nm in names:
            nm = str(nm).strip()
            if nm and len(nm) >= 4 and nm.lower() in low:
                issues.append(Issue(
                    post.sheet, post.row, "Пост", Level.ERROR, "text_other_name",
                    f"В тексте упомянуто название другого бренда — «{nm}» ({other}).",
                    "Проверьте: вероятно, шаблон скопирован от другого бренда.",
                    brand=code, post_type=post.post_type,
                ))
                break
    return issues


# ---------------------------------------------------------------------------
# Хэштеги
# ---------------------------------------------------------------------------
def check_required_hashtags(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    b = brands.get(code, {})
    required = b.get("required_hashtags_shipment", [])
    canon_type, _ = N.canonical_post_type(post.post_type,
                                           rules.get("post_type_canonical", {}))
    # хэштеги требуются, если это включено в правилах типа (бренд × тип)
    if not type_rules_for(code, canon_type, brands, rules)["hashtags"] or not required:
        return []
    tags = {t.lower() for t in _hashtags(post.text)}
    missing = [h for h in required if h.lower() not in tags]
    if missing:
        return [Issue(
            post.sheet, post.row, "Пост", Level.WARNING, "text_missing_hashtags",
            f"Нет обязательных хэштегов отгрузки: {', '.join(missing)}.",
            "Добавьте недостающие хэштеги бренда.",
            brand=code, post_type=post.post_type,
        )]
    return []


def check_mpi_first_hashtag(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    b = brands.get(code, {})
    first_must = b.get("first_hashtag_must_be")
    if not first_must:
        return []
    tags = _hashtags(post.text)
    if tags and tags[0].lower() != first_must.lower():
        return [Issue(
            post.sheet, post.row, "Пост", Level.WARNING, "text_mpi_first",
            f"Первым хэштегом должен быть {first_must}, а стоит {tags[0]}.",
            f"Поставьте {first_must} первым хэштегом.",
            brand=code, post_type=post.post_type,
        )]
    return []


def check_repeated_hashtag(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    tags = [t.lower() for t in _hashtags(post.text)]
    issues = []
    seen = set()
    for t in tags:
        if t in seen:
            issues.append(Issue(
                post.sheet, post.row, "Пост", Level.ADVICE, "text_dup_hashtag",
                f"Хэштег {t} повторяется.",
                "Уберите повтор хэштега.",
                brand=code, post_type=post.post_type,
            ))
            break
        seen.add(t)
    return issues


def check_weird_hashtag(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    issues = []
    for t in _hashtags(post.text):
        body = t[1:]
        if re.search(r"\d$", body) or re.search(r"[^\wА-Яа-яЁё]", body):
            issues.append(Issue(
                post.sheet, post.row, "Пост", Level.WARNING, "text_weird_hashtag",
                f"Подозрительный хэштег: {t} (заканчивается цифрой или содержит "
                "странные символы).",
                "Проверьте хэштег — возможно, опечатка (например, лишняя цифра).",
                brand=code, post_type=post.post_type,
            ))
    return issues


# ---------------------------------------------------------------------------
# Остатки шаблонов и промтов
# ---------------------------------------------------------------------------
def check_placeholders(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    pattern = rules.get("placeholder_pattern", r"\[[^\]]+\]")
    found = re.findall(pattern, post.text)
    # не считаем ссылки в скобках markdown вида [текст](url) — но здесь [..] без ()
    real = [f for f in found if not re.match(r"\[[^\]]+\]\(", post.text[post.text.find(f):post.text.find(f)+len(f)+1])]
    issues = []
    for f in set(real):
        issues.append(Issue(
            post.sheet, post.row, "Пост", Level.ERROR, "text_placeholder",
            f"Незаполненная заглушка из шаблона: {f}",
            "Замените заглушку в квадратных скобках на реальные данные.",
            brand=code, post_type=post.post_type,
        ))
    return issues


def check_prompt_leftovers(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    phrases = rules.get("prompt_leftover_phrases", [])
    low = post.text.lower()
    issues = []
    for ph in phrases:
        if ph.lower() in low:
            issues.append(Issue(
                post.sheet, post.row, "Пост", Level.ERROR, "text_prompt",
                f"В тексте остался кусок промта/инструкции: «{ph}».",
                "Уберите служебный текст — это инструкция для нейросети, а не пост.",
                brand=code, post_type=post.post_type,
            ))
    return issues


def check_markdown_stars(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    if re.search(r"\*[^*\n]+\*", post.text):
        return [Issue(
            post.sheet, post.row, "Пост", Level.WARNING, "text_stars",
            "В тексте остались звёздочки разметки *…* (после нейросети).",
            "Уберите звёздочки или замените на настоящее выделение для соцсети.",
            brand=code, post_type=post.post_type,
        )]
    return []


# ---------------------------------------------------------------------------
# Оформление и типографика
# ---------------------------------------------------------------------------
def check_long_dashes(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    limit = rules.get("thresholds", {}).get("long_dash_max", 3)
    cnt = post.text.count("—")
    if cnt > limit:
        return [Issue(
            post.sheet, post.row, "Пост", Level.ADVICE, "text_dashes",
            f"Много длинных тире «—»: {cnt} (порог {limit}).",
            "По правилу используйте меньше длинных тире.",
            brand=code, post_type=post.post_type,
        )]
    return []


def check_colon_in_list(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    if code not in rules.get("list_colon_brands", []):
        return []
    markers = rules.get("list_bullet_markers", [])
    issues = []
    for i, line in enumerate(_lines(post.text)):
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(m) for m in markers) and ":" in stripped:
            issues.append(Issue(
                post.sheet, post.row, "Пост", Level.WARNING, "text_list_colon",
                f"Двоеточие внутри пункта списка (строка «{stripped[:40]}…»).",
                f"Для бренда {code} в пунктах списка двоеточие не ставят.",
                brand=code, post_type=post.post_type,
            ))
            break
    return issues


def check_whitespace(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    text = post.text
    issues = []
    if "  " in text:
        issues.append(Issue(
            post.sheet, post.row, "Пост", Level.ADVICE, "text_double_space",
            "В тексте есть двойные пробелы.",
            "Замените двойные пробелы на одинарные.",
            brand=code, post_type=post.post_type,
        ))
    if any(l != l.rstrip() for l in _lines(text)):
        issues.append(Issue(
            post.sheet, post.row, "Пост", Level.ADVICE, "text_trailing_space",
            "Есть пробелы в конце строк.",
            "Уберите лишние пробелы в конце строк.",
            brand=code, post_type=post.post_type,
        ))
    max_blank = rules.get("thresholds", {}).get("max_blank_lines", 2)
    if re.search(r"\n{" + str(max_blank + 2) + r",}", text):
        issues.append(Issue(
            post.sheet, post.row, "Пост", Level.ADVICE, "text_blank_lines",
            f"Три и более пустых строки подряд.",
            "Сократите количество пустых строк.",
            brand=code, post_type=post.post_type,
        ))
    return issues


def check_doubled_letter(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    # удвоенная буква в начале слова с разным регистром: «Рработает»
    issues = []
    for m in re.finditer(r"\b([А-ЯЁA-Z])(\1)", post.text, re.IGNORECASE):
        word_start = m.start()
        w = re.match(r"[\wА-Яа-яЁё]+", post.text[word_start:])
        word = w.group(0) if w else post.text[word_start:word_start+10]
        # именно разный регистр первых двух букв
        if post.text[m.start()] != post.text[m.start()+1] and \
           post.text[m.start()].lower() == post.text[m.start()+1].lower():
            issues.append(Issue(
                post.sheet, post.row, "Пост", Level.WARNING, "text_doubled_letter",
                f"Похоже на опечатку — удвоенная буква в начале слова: «{word}».",
                "Проверьте слово и уберите лишнюю букву.",
                brand=code, post_type=post.post_type,
            ))
    return issues


def check_doubled_word(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    issues = []
    for m in re.finditer(r"\b([А-Яа-яЁёA-Za-z]+)\s+\1\b", post.text):
        w = m.group(1)
        if len(w) >= 1:
            issues.append(Issue(
                post.sheet, post.row, "Пост", Level.WARNING, "text_doubled_word",
                f"Два одинаковых слова подряд: «{w} {w}».",
                "Уберите повтор слова.",
                brand=code, post_type=post.post_type,
            ))
    return issues


def check_mixed_quotes(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    has_elki = "«" in post.text or "»" in post.text
    has_lapki = '"' in post.text
    if has_elki and has_lapki:
        return [Issue(
            post.sheet, post.row, "Пост", Level.ADVICE, "text_mixed_quotes",
            "В тексте смешаны кавычки-«ёлочки» и \"лапки\".",
            "Приведите кавычки к одному виду (обычно «ёлочки»).",
            brand=code, post_type=post.post_type,
        )]
    return []


def check_hard_wraps(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    lines = _lines(post.text)
    issues = []
    for i in range(len(lines) - 1):
        cur = lines[i].rstrip()
        nxt = lines[i + 1].lstrip()
        if not cur or not nxt:
            continue
        # текущая строка не заканчивается знаком препинания, следующая с маленькой буквы
        if cur[-1] not in ".!?:;…»)\"" and nxt[:1].islower() and \
           not nxt.startswith(("#", "http", "•", "-", "→")):
            issues.append(Issue(
                post.sheet, post.row, "Пост", Level.WARNING, "text_hard_wrap",
                f"Жёсткий перенос строки посреди предложения (после «…{cur[-30:]}»).",
                "В соцсети текст будет выглядеть рвано. Соедините строки в одно предложение.",
                brand=code, post_type=post.post_type,
            ))
            break
    return issues


# ---------------------------------------------------------------------------
# Длина и ссылки
# ---------------------------------------------------------------------------
def check_telegram_length(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    th = rules.get("thresholds", {})
    caption = th.get("telegram_caption_limit", 1024)
    length = len(post.text)
    has_photo = bool(post.photos)
    if has_photo and length > caption:
        return [Issue(
            post.sheet, post.row, "Пост", Level.WARNING, "text_tg_caption",
            f"Текст длиннее лимита подписи к фото в Telegram "
            f"({length} > {caption} символов).",
            "Текст не поместится под картинкой и уйдёт отдельным сообщением. "
            "Сократите текст или отправьте фото отдельно.",
            brand=code, post_type=post.post_type,
        )]
    return []


def check_link_domain(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    b = brands.get(code, {})
    own_site = str(b.get("site", "")).lower()
    issues = []
    for url in N.extract_links(post.text):
        d = N.link_domain(url)
        # ссылки на соцсети и картинки не считаем «чужим доменом»
        if d in {"t.me", "telegram.me", "vk.com", "ok.ru", "dzen.ru", "max.ru",
                 "ibb.co", "i.ibb.co", "drive.google.com"}:
            continue
        if own_site and own_site not in d and d not in own_site:
            # чужой сайт бренда?
            other_brand_sites = {str(v.get("site", "")).lower()
                                 for k, v in brands.items() if k != code}
            if d in other_brand_sites:
                issues.append(Issue(
                    post.sheet, post.row, "Пост", Level.WARNING, "text_foreign_domain",
                    f"Ссылка в тексте ведёт на сайт другого бренда: {d}.",
                    "Замените на ссылку на сайт своего бренда.",
                    brand=code, post_type=post.post_type, link=url,
                ))
    return issues


def check_info_needs_link(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    # Ссылка на сайт в инфопосте теперь проверяется в check_contacts_present
    # с учётом правил бренд × тип и ссылки-анкора. Оставлено для совместимости.
    return []


# ---------------------------------------------------------------------------
# Сноска про цену и оферту (спецпредложения)
# ---------------------------------------------------------------------------
def _norm_footnote(t: str) -> str:
    t = re.sub(r"^[^\wА-Яа-яЁё]+", "", t or "")  # убрать ведущие эмодзи/символы
    return re.sub(r"\s+", " ", t).strip().lower()


def _has_price(text: str) -> bool:
    low = (text or "").lower()
    if "скидк" in low:
        return True
    return bool(re.search(r"\d[\d\s.,]*\s*(?:₽|руб|р\.|%)", text or "", re.IGNORECASE))


def check_offer_footnote(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    b = brands.get(code, {})
    footnote = str(b.get("offer_footnote", "")).strip()
    if not footnote:
        return []
    canon_type, _ = N.canonical_post_type(post.post_type,
                                          rules.get("post_type_canonical", {}))
    req_types = rules.get("footnote_required_types", ["Спецпредложение"])
    if canon_type not in req_types and not _has_price(post.text):
        return []
    text_norm = _norm_footnote(post.text)
    if _norm_footnote(footnote) not in text_norm:
        return [Issue(
            post.sheet, post.row, "Пост", Level.WARNING, "text_offer_footnote",
            "В посте с ценой/спецпредложением нет обязательной сноски про цену "
            "и оферту.",
            f"Добавьте отдельной строкой перед хэштегами: «{footnote}»",
            brand=code, post_type=post.post_type,
        )]
    # сноска есть — проверим, что перед ней нет звёздочки (слетает при автопостинге)
    for line in post.text.split("\n"):
        ln = line.strip()
        if ln.startswith("*") and _norm_footnote(footnote) in _norm_footnote(ln):
            return [Issue(
                post.sheet, post.row, "Пост", Level.ADVICE, "text_footnote_star",
                "Перед сноской стоит звёздочка «*» — она может слететь при "
                "автопостинге.",
                "Уберите «*», оставьте сноску просто отдельной строкой.",
                brand=code, post_type=post.post_type,
            )]
    return []


# ---------------------------------------------------------------------------
# Короткое тире вместо длинного
# ---------------------------------------------------------------------------
def check_short_dash(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    # короткое тире «–» между словами (с пробелами) должно быть длинным «—»
    if re.search(r"\s–\s", post.text or ""):
        return [Issue(
            post.sheet, post.row, "Пост", Level.WARNING, "text_short_dash",
            "В тексте короткое тире «–» вместо длинного «—» "
            "(например, «сталь – ежедневно»).",
            "В русской типографике между словами ставится длинное «—».",
            brand=code, post_type=post.post_type,
        )]
    return []


# ---------------------------------------------------------------------------
# Фото отгрузок: нужны обе строки ЛОГО и БЕЗ ЛОГО
# ---------------------------------------------------------------------------
def check_shipment_photo_labels(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    canon_type, _ = N.canonical_post_type(post.post_type,
                                          rules.get("post_type_canonical", {}))
    if canon_type != "Отгрузка" or not post.photos:
        return []
    has_logo = any(p.strip().upper().startswith("ЛОГО:") for p in post.photos)
    has_nologo = any(p.strip().upper().startswith("БЕЗ ЛОГО:") for p in post.photos)
    missing = []
    if not has_logo:
        missing.append("«ЛОГО:»")
    if not has_nologo:
        missing.append("«БЕЗ ЛОГО:»")
    if missing:
        return [Issue(
            post.sheet, post.row, "Фото", Level.WARNING, "text_shipment_labels",
            f"У отгрузки не хватает строк фото: {', '.join(missing)}.",
            "Для отгрузки нужны обе строки: «ЛОГО:» (в соцсети) и «БЕЗ ЛОГО:» "
            "(Яндекс Бизнес).",
            brand=code, post_type=post.post_type,
        )]
    return []


# ---------------------------------------------------------------------------
# Фото
# ---------------------------------------------------------------------------
def check_photo_empty(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    canon_type, _ = N.canonical_post_type(post.post_type,
                                          rules.get("post_type_canonical", {}))
    if canon_type == "Дзен":
        return []
    if not post.photos:
        return [Issue(
            post.sheet, post.row, "Фото", Level.WARNING, "text_no_photo",
            "У поста не указано фото.",
            "Добавьте ссылку на картинку (или уточните, что фото не нужно).",
            brand=code, post_type=post.post_type,
        )]
    return []


def check_post_type_spelling(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    mapping = rules.get("post_type_canonical", {})
    if not post.post_type:
        return []
    canon, literal = N.canonical_post_type(post.post_type, mapping)
    if not literal and canon:
        return [Issue(
            post.sheet, post.row, "Тип", Level.WARNING, "text_type_spelling",
            f"Тип поста записан как «{post.post_type}», эталон — «{canon}».",
            f"Приведите написание к «{canon}» для единообразия.",
            brand=code, post_type=post.post_type,
        )]
    return []


def check_photo_filename(post: PostRecord, code: str, brands, rules) -> list[Issue]:
    issues = []
    for ph in post.photos:
        val = re.sub(r"^(ЛОГО:|БЕЗ ЛОГО:|ЯБ:|СОЦ:)\s*", "", ph).strip()
        if "http" not in val.lower() and re.search(r"\.(jpg|jpeg|png|gif|webp)$",
                                                    val, re.IGNORECASE):
            issues.append(Issue(
                post.sheet, post.row, "Фото", Level.WARNING, "text_photo_name",
                f"Вместо ссылки указано имя файла: «{val}».",
                "Картинку не найти по имени файла — вставьте ссылку на изображение.",
                brand=code, post_type=post.post_type,
            ))
    return issues


# --- реестр проверок текстов ---
TEXT_CHECKS = [
    ("text_contacts_present", check_contacts_present),
    ("text_offer_footnote", check_offer_footnote),
    ("text_short_dash", check_short_dash),
    ("text_shipment_labels", check_shipment_photo_labels),
    ("text_other_brand_contacts", check_other_brand_contacts),
    ("text_other_brand_name", check_other_brand_name),
    ("text_required_hashtags", check_required_hashtags),
    ("text_mpi_first_hashtag", check_mpi_first_hashtag),
    ("text_repeated_hashtag", check_repeated_hashtag),
    ("text_weird_hashtag", check_weird_hashtag),
    ("text_placeholders", check_placeholders),
    ("text_prompt_leftovers", check_prompt_leftovers),
    ("text_markdown_stars", check_markdown_stars),
    ("text_long_dashes", check_long_dashes),
    ("text_colon_in_list", check_colon_in_list),
    ("text_whitespace", check_whitespace),
    ("text_doubled_letter", check_doubled_letter),
    ("text_doubled_word", check_doubled_word),
    ("text_mixed_quotes", check_mixed_quotes),
    ("text_hard_wraps", check_hard_wraps),
    ("text_telegram_length", check_telegram_length),
    ("text_link_domain", check_link_domain),
    ("text_photo_empty", check_photo_empty),
    ("text_photo_filename", check_photo_filename),
    ("registry_post_type_spelling", check_post_type_spelling),
]


def run_text_checks(posts_by_brand: dict[str, list[PostRecord]],
                    brands: dict, rules: dict) -> list[Issue]:
    toggles = rules.get("toggles", {})
    issues: list[Issue] = []
    for code, posts in posts_by_brand.items():
        for post in posts:
            if not post.text.strip():
                continue
            for key, fn in TEXT_CHECKS:
                if not toggles.get(key, True):
                    continue
                try:
                    issues.extend(fn(post, code, brands, rules))
                except Exception as e:  # noqa: BLE001
                    issues.append(Issue(
                        post.sheet, post.row, "", Level.TECH, f"tech_{key}",
                        f"Проверка «{key}» не сработала на строке {post.row}: {e}",
                        "Остальные проверки выполнены.",
                        brand=code,
                    ))
    return issues
