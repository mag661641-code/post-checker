"""Проверка картинок отгрузок (СМУ, ИМП, МПЭ …).

Порт «Модуля 2» из проекта автоматизации SMM. Сверяет имена картинок в реестре
с файлами в папке Google Диска бренда: недопустимые имена, транслит, дубли и
пропуски номеров, отсутствие .jpg/.webp, тяжёлые файлы, «сироты» на Диске,
опечатки (по Левенштейну). Опционально — доступность картинок на сайте.

Этот модуль — чистая логика без сети и без Streamlit (проверяется тестами):
на вход уже загруженные имена из реестра и список файлов с Диска, на выход —
список проблем. Загрузку из Google делает checker/shipment_io.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from .models import Level

# Цвета строк для таблицы/Excel по уровню (ARGB для openpyxl)
LEVEL_COLOR = {Level.ERROR: "FFF8D7DA", Level.WARNING: "FFFFF3CD"}


@dataclass
class ImgProblem:
    brand: str
    level: Level
    what: str
    name: str = ""
    reg_row: Any = ""
    disk: str = ""
    hint: str = ""
    url: str = ""


# ---------------------------------------------------------------------------
# Имена картинок: разбор и валидация
# ---------------------------------------------------------------------------
def strip_extension(name: str) -> str:
    """Убрать расширение картинки: 'foto.webp' → 'foto'."""
    return re.sub(r"\.(jpe?g|webp|png)$", "", str(name), flags=re.IGNORECASE)


def bad_chars(s: str) -> str:
    """Человеческим языком перечислить, что не так в имени картинки."""
    uniq: list[str] = []
    for c in re.sub(r"[a-z0-9-]", "", s):
        label = "«пробел»" if c == " " else "«%s»" % c
        if label not in uniq:
            uniq.append(label)
    bad = list(uniq)
    if re.search(r"--", s):
        bad.append("двойной дефис")
    if re.search(r"^-|-$", s):
        bad.append("дефис в начале/конце")
    if re.search(r"[A-Z]", s):
        bad.append("заглавные буквы")
    return ", ".join(bad) if bad else "нарушен формат"


def validate_image_name(name: str) -> dict[str, list[str]]:
    """Проверить одно имя картинки. {'errors': [...], 'warnings': [...]}.

    Разрешены только строчные латинские буквы, цифры и одиночные дефисы.
    Одиночная «c» (не «ch») — предупреждение о транслите «ц» (ts)."""
    errors: list[str] = []
    warnings: list[str] = []
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name):
        errors.append(
            "Недопустимые символы в имени: %s. Допустимы только латинские "
            "строчные буквы, цифры и одиночные дефисы. На сайте такая картинка "
            "будет битой." % bad_chars(name))
    if re.search(r"c(?!h)", name):
        warnings.append(
            "Возможно, буква «ц» записана как «c» вместо «ts». Сверьте с адресом "
            "категории на сайте (например, otsinkovannaya, flantsy).")
    return {"errors": errors, "warnings": warnings}


def levenshtein(a: str, b: str) -> int:
    m, n = len(a), len(b)
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[n]


def find_similar(name: str, candidates: list[str],
                 max_diff: int) -> Optional[dict]:
    """Самое похожее имя среди кандидатов: {'name':..., 'd':...} или None."""
    best = None
    for c in candidates:
        if abs(len(c) - len(name)) > max_diff:
            continue
        d = levenshtein(name, c)
        if d <= max_diff and (best is None or d < best["d"]):
            best = {"name": c, "d": d}
    return best


# ---------------------------------------------------------------------------
# Чтение эталонных имён из сетки листа бренда
# ---------------------------------------------------------------------------
def read_expected_from_grid(grid: list[list[Any]], name_col: int,
                            first_data_row: int, jpg_col: Optional[int] = None,
                            webp_col: Optional[int] = None) -> list[dict]:
    """Собрать имена картинок из матрицы значений листа.

    Индексы столбцов 0-based, first_data_row — 0-based индекс первой строки.
    Возвращает список {name, raw, row, jpg_url, webp_url}."""
    out = []
    for i in range(first_data_row, len(grid)):
        row = grid[i]
        raw = row[name_col] if name_col < len(row) and \
            row[name_col] is not None else ""
        if str(raw).strip() == "":
            continue
        raw = str(raw)

        def _cell(col):
            if col is None or col < 0 or col >= len(row) or row[col] is None:
                return ""
            return str(row[col]).strip()

        out.append({
            "raw": raw,
            "name": strip_extension(raw.strip()),
            "row": i + 1,
            "jpg_url": _cell(jpg_col),
            "webp_url": _cell(webp_col),
        })
    return out


# ---------------------------------------------------------------------------
# Проверка одного бренда
# ---------------------------------------------------------------------------
def check_one_brand(brand: str, expected: list[dict], drive: dict,
                    brand_cfg: dict, max_kb: int,
                    fuzzy_max_diff: int) -> dict:
    """Проверить один бренд.

    expected — [{name, raw, row, jpg_url, webp_url}, ...].
    drive — {base -> [{name, ext, size_kb, url}, ...]}.
    Возвращает {brand, expected_count, files_count, problems: [ImgProblem]}.
    """
    problems: list[ImgProblem] = []

    def add(level, what, name="", reg_row="", disk="", hint="", url=""):
        problems.append(ImgProblem(brand, level, what, name, reg_row, disk,
                                   hint, url))

    if not expected:
        add(Level.WARNING, "В реестре нет имён",
            hint="Лист «%s», столбец с именем пуст. Проверьте настройки."
                 % brand_cfg.get("sheet", brand))
        return {"brand": brand, "expected_count": 0, "files_count": 0,
                "problems": problems}

    files_count = sum(len(v) for v in drive.values())

    # 1. Сами имена
    seen: dict[str, Any] = {}
    numbers = []
    for e in expected:
        if e["raw"] != e["raw"].strip():
            add(Level.WARNING, "Пробел в начале/конце имени", name=e["name"],
                reg_row=e["row"], hint="Удалите пробелы в ячейке реестра.")
        v = validate_image_name(e["name"])
        for m in v["errors"]:
            add(Level.ERROR, "Недопустимое имя", name=e["name"],
                reg_row=e["row"], hint=m)
        for m in v["warnings"]:
            add(Level.WARNING, "Проверьте транслит", name=e["name"],
                reg_row=e["row"], hint=m)

        if e["name"] in seen:
            add(Level.ERROR, "Дубль имени в реестре", name=e["name"],
                reg_row=e["row"],
                hint="Такое же имя уже в строке %s." % seen[e["name"]])
        else:
            seen[e["name"]] = e["row"]

        m = re.search(r"-(\d+)$", e["name"])
        if m:
            numbers.append({"n": int(m.group(1)), "name": e["name"],
                            "row": e["row"]})

    # 2. Номера: повторы и пропуски
    numbers.sort(key=lambda x: x["n"])
    for i in range(1, len(numbers)):
        prev, cur = numbers[i - 1], numbers[i]
        if cur["n"] == prev["n"]:
            add(Level.ERROR, "Повтор номера", name=cur["name"],
                reg_row=cur["row"],
                hint="Номер %d уже есть у «%s»." % (cur["n"], prev["name"]))
        elif cur["n"] - prev["n"] > 1:
            gap = str(prev["n"] + 1)
            if cur["n"] - prev["n"] > 2:
                gap += "–%d" % (cur["n"] - 1)
            add(Level.WARNING, "Пропуск в нумерации", name=cur["name"],
                reg_row=cur["row"],
                hint="После %d сразу идёт %d. Пропущены номера %s."
                     % (prev["n"], cur["n"], gap))

    # 3. Сверка реестра с Диском
    expected_names = [e["name"] for e in expected]
    expected_set = set(expected_names)
    orphan_bases = [b for b in drive.keys() if b not in expected_set]

    for e in expected:
        files = drive.get(e["name"], [])
        if not files:
            hint = find_similar(e["name"], orphan_bases, fuzzy_max_diff)
            hint_url = drive[hint["name"]][0]["url"] if hint else ""
            add(Level.ERROR, "Нет на Диске", name=e["name"], reg_row=e["row"],
                hint=("Похожий файл на Диске: «%s» (отличается символов: %d). "
                      "Скорее всего опечатка." % (hint["name"], hint["d"]))
                     if hint else "Похожих файлов не найдено.", url=hint_url)
            continue

        exts = [f["ext"].lower() for f in files]
        names_joined = ", ".join(f["name"] for f in files)
        if brand_cfg.get("require_jpg") and "jpg" not in exts \
                and "jpeg" not in exts:
            add(Level.ERROR, "Нет .jpg", name=e["name"], reg_row=e["row"],
                disk=names_joined,
                hint="Есть только: %s. Добавьте .jpg." % ", ".join(exts))
        if brand_cfg.get("require_webp") and "webp" not in exts:
            add(Level.ERROR, "Нет .webp", name=e["name"], reg_row=e["row"],
                disk=names_joined,
                hint="Сконвертируйте jpg в webp (нужны оба формата).")

        for f in files:
            lower = f["ext"].lower()
            if lower not in ("jpg", "jpeg", "webp"):
                add(Level.ERROR, "Неверное расширение .%s" % f["ext"],
                    name=e["name"], reg_row=e["row"], disk=f["name"],
                    hint="Разрешены только .jpg и .webp. Формат %s запрещён — "
                         "пересохраните в JPG." % f["ext"], url=f["url"])
            elif f["ext"] != lower:
                add(Level.ERROR, "Расширение заглавными (.%s)" % f["ext"],
                    name=e["name"], reg_row=e["row"], disk=f["name"],
                    hint="Для сайта «.JPG» и «.jpg» — разные файлы. Переименуйте "
                         "расширение строчными.", url=f["url"])
            if f["size_kb"] > max_kb:
                add(Level.WARNING, "Тяжёлый файл", name=e["name"],
                    reg_row=e["row"], disk="%s — %d кб" % (f["name"], f["size_kb"]),
                    hint="Лимит %d кб. Сожмите (tinypng / squoosh)." % max_kb,
                    url=f["url"])

        cnt: dict[str, int] = {}
        for f in files:
            cnt[f["name"]] = cnt.get(f["name"], 0) + 1
        for n, c in cnt.items():
            if c > 1:
                add(Level.WARNING, "Копии на Диске", name=e["name"],
                    reg_row=e["row"], disk="%s × %d" % (n, c),
                    hint="Один и тот же файл лежит несколько раз (в разных "
                         "подпапках). Оставьте один.")

    # 4. «Сироты»: на Диске есть, в реестре нет
    for base in orphan_bases:
        files = drive[base]
        hint = find_similar(base, expected_names, fuzzy_max_diff)
        add(Level.WARNING, "Есть на Диске, нет в реестре",
            disk=", ".join(f["name"] for f in files),
            hint=("Похоже на «%s» из реестра (отличается символов: %d)."
                  % (hint["name"], hint["d"]))
                 if hint else "Добавьте имя в реестр или уберите файл с Диска.",
            url=files[0]["url"])

    return {"brand": brand, "expected_count": len(expected),
            "files_count": files_count, "problems": problems}


def evaluate_site_response(status_code: Optional[int], headers: dict, url: str,
                           brand: str, name: str,
                           reg_row: Any) -> Optional[ImgProblem]:
    """Разобрать ответ сайта. Возвращает ImgProblem или None (если всё ок)."""
    def h(key):
        for k, v in (headers or {}).items():
            if k.lower() == key.lower():
                return v
        return ""

    def mk(level, what, hint=""):
        return ImgProblem(brand, level, what, name=name, reg_row=reg_row,
                          hint=hint, url=url)

    if status_code is None:
        return mk(Level.ERROR, "Сайт не ответил",
                  "Не удалось открыть %s. Проверьте вручную." % url)
    ctype = str(h("Content-Type"))
    if status_code == 404:
        return mk(Level.ERROR, "На сайте 404 (битая картинка)",
                  "Картинка не найдена: %s" % url)
    if 300 <= status_code < 400:
        return mk(Level.WARNING, "На сайте редирект %d" % status_code,
                  "%s → %s" % (url, h("Location") or "?"))
    if status_code != 200:
        return mk(Level.ERROR, "На сайте ответ %d" % status_code,
                  "Проверьте ссылку: %s" % url)
    if "image" not in ctype:
        return mk(Level.ERROR, "Сайт отдаёт не картинку",
                  "Тип ответа: %s. %s" % (ctype or "неизвестен", url))
    return None


def count_errors(images_result: dict) -> int:
    n = 0
    for br in images_result["per_brand"]:
        n += sum(1 for p in br["problems"] if p.level == Level.ERROR)
    n += sum(1 for p in images_result.get("site", []) if p.level == Level.ERROR)
    return n


def count_warnings(images_result: dict) -> int:
    n = 0
    for br in images_result["per_brand"]:
        n += sum(1 for p in br["problems"] if p.level == Level.WARNING)
    n += sum(1 for p in images_result.get("site", []) if p.level == Level.WARNING)
    return n
