"""Проверка дублей идей постов.

Порт скрипта Google Apps Script («Проверка дублей идей, версия 3») на Python.
Ищет повторы тем в листе «Идеи» реестра двумя способами:

* по словам (лексически) — нормализация, лёгкий стеммер, Жаккар/overlap/
  Левенштейн. Работает всегда, без интернета и без ключей;
* по смыслу (семантически) — косинус между эмбеддингами Gemini. Включается
  отдельно и требует ключа Google AI (см. checker/embeddings.py).

Модуль не зависит от Streamlit и от сети — только чистые вычисления, поэтому
проверяется тестами. Векторы приходят снаружи готовыми (dict row -> vector).

Вердикты (как в исходном скрипте):
    🔴 ЗАНЯТО      — дубль уже опубликован (заполнен столбец «Выложено»)
    🟠 ЕСТЬ В ПЛАНЕ — дубль есть, но ещё не вышел
    🟡 ПОХОЖЕ      — близкая тема, посмотреть глазами
    🟢 СВОБОДНО    — ничего похожего
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Пороги (значения по умолчанию перенесены из скрипта)
# ---------------------------------------------------------------------------
@dataclass
class Thresholds:
    """Пороги срабатывания. Настраиваются через config/dedup.json."""
    dup_limit: float = 0.70       # по словам: дубль
    sim_limit: float = 0.50       # по словам: похоже
    sem_dup_limit: float = 0.90   # по смыслу: дубль
    sem_sim_limit: float = 0.85   # по смыслу: похоже
    max_idea_length: int = 400    # длиннее — это бриф/шаблон, не идея, пропускаем


DEFAULT_THRESHOLDS = Thresholds()

# Статус -> (эмодзи-метка, цвет строки для таблицы/Excel)
STATUS_LABEL = {
    "taken": "🔴 Занято",
    "planned": "🟠 Есть в плане",
    "similar": "🟡 Похоже",
    "free": "🟢 Свободно",
    "skipped": "⚪ Пропущено",
}
STATUS_COLOR = {
    "taken": "FFF4C7C3",
    "planned": "FFFCE5CD",
    "similar": "FFFFF2CC",
    "free": "FFD9EAD3",
    "skipped": "FFF3F3F3",
}
# порядок серьёзности — для сортировки и сводки
STATUS_ORDER = ["taken", "planned", "similar", "free", "skipped"]


# ---------------------------------------------------------------------------
# Обработка текста: нормализация, стеммер, множество основ
# ---------------------------------------------------------------------------
STOP_WORDS = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то",
    "все", "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за",
    "бы", "по", "только", "ее", "мне", "было", "вот", "от", "меня", "еще",
    "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну", "вдруг", "ли",
    "если", "уже", "или", "ни", "быть", "был", "него", "до", "вас", "нибудь",
    "опять", "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей",
    "может", "они", "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя",
    "их", "чем", "была", "сам", "чтоб", "без", "будто", "чего", "раз", "тоже",
    "себе", "под", "будет", "тогда", "кто", "этот", "того", "потому", "этого",
    "какой", "совсем", "ним", "здесь", "этом", "один", "почти", "мой", "тем",
    "чтобы", "нее", "сейчас", "были", "куда", "зачем", "всех", "никогда",
    "можно", "при", "наконец", "два", "об", "другой", "хоть", "после", "над",
    "больше", "тот", "через", "эти", "нас", "про", "всего", "них", "какая",
    "много", "разве", "эту", "моя", "впрочем", "хорошо", "свою", "этой",
    "перед", "иногда", "лучше", "чуть", "том", "нельзя", "такой", "им",
    "более", "всегда", "конечно", "всю", "между",
    # частые «мусорные» для контент-плана слова
    "топ", "лайфхак", "гайд", "подборка", "обзор", "инструкция", "своими",
    "пост", "видео",
}

# Окончания для лёгкого стемминга (от длинных к коротким — важно для корректной
# отрезки). Отрезаем только если остаётся основа не короче 4 символов.
_ENDINGS = [
    "ированием", "ированный", "ирования", "ированию", "ировании", "ирование",
    "ировать", "ениями", "ениях", "ением", "ениям", "остями", "остям",
    "остях", "ами", "ями", "ого", "его", "ому", "ему", "ыми", "ими", "ыть",
    "ить", "ать", "ять", "еть", "ния", "нию", "нии", "ние", "ний", "ешь",
    "ишь", "ей", "ов", "ев", "ий", "ый", "ой", "ая", "яя", "ое", "ее", "ые",
    "ие", "ам", "ям", "ом", "ем", "ах", "ях", "ую", "юю", "ся", "ть", "ла",
    "ло", "ли", "ет", "ут", "ют", "ит", "ат", "ят", "а", "я", "о", "е", "у",
    "ю", "ы", "и", "ь", "й",
]


def letter_to_index(letter: str) -> int:
    """Буква столбца → индекс 0-based. 'A'→0, 'C'→2, 'K'→10, 'AA'→26."""
    s = str(letter).strip().upper()
    if not re.fullmatch(r"[A-Z]+", s):
        raise ValueError("Неверная буква столбца: «%s». Впишите латинскую букву "
                         "(например C или K)." % letter)
    idx = 0
    for ch in s:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def normalize(text: Any) -> str:
    """Привести к сравнимому виду: нижний регистр, ё→е, только буквы/цифры."""
    s = str(text or "").lower().replace("ё", "е")
    s = re.sub(r"[^a-zа-я0-9\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def stem(word: str) -> str:
    """Отрезать типовое русское окончание (оставив основу ≥ 4 символов)."""
    for end in _ENDINGS:
        if len(word) - len(end) >= 4 and word.endswith(end):
            return word[: len(word) - len(end)]
    return word


def stem_set(text: Any) -> list[str]:
    """Множество значимых основ слов (без стоп-слов и коротышей)."""
    out: list[str] = []
    for w in normalize(text).split(" "):
        if len(w) < 3 or w in STOP_WORDS:
            continue
        s = stem(w)
        if s not in out:
            out.append(s)
    return out


# ---------------------------------------------------------------------------
# Расстояния и похожесть
# ---------------------------------------------------------------------------
def levenshtein(a: str, b: str) -> int:
    m, n = len(a), len(b)
    if m == 0:
        return n
    if n == 0:
        return m
    prev = list(range(n + 1))
    for i in range(1, m + 1):
        cur = [i] + [0] * n
        for j in range(1, n + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[n]


def levenshtein_ratio(a: str, b: str) -> float:
    m = max(len(a), len(b))
    if m == 0:
        return 1.0
    return 1 - levenshtein(a, b) / m


def lexical_similarity(norm_a: str, stems_a: list[str],
                       norm_b: str, stems_b: list[str]) -> float:
    """Похожесть двух идей по словам (0..1). Формула из исходного скрипта:
    смесь Жаккара и Левенштейна, плюс overlap для случая «короткая идея целиком
    входит в длинную». Overlap считаем только при ≥3 значимых словах в короткой
    идее — иначе «Логотип ИИ» ложно совпадёт со всем, где есть «логотип»."""
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0
    set_b = set(stems_b)
    inter = sum(1 for s in stems_a if s in set_b)
    union = len(stems_a) + len(stems_b) - inter
    jaccard = inter / union if union > 0 else 0.0
    min_len = min(len(stems_a), len(stems_b))
    overlap = inter / min_len if min_len >= 3 else 0.0
    lev = levenshtein_ratio(norm_a, norm_b)
    return max(0.7 * jaccard + 0.3 * lev, 0.85 * overlap)


def cosine(a: Optional[list[float]], b: Optional[list[float]]) -> float:
    """Косинус между векторами (ожидаются уже нормированные). 0..1."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    return max(0.0, min(1.0, dot))


# ---------------------------------------------------------------------------
# Идея и вердикт
# ---------------------------------------------------------------------------
@dataclass
class Idea:
    row: int                       # строка Excel (для ссылки «открыть»)
    raw: str                       # исходный текст идеи
    published: str = ""            # значение столбца «Выложено» (пусто = не вышло)
    usable: bool = field(init=False, default=False)
    norm: str = field(init=False, default="")
    stems: list[str] = field(init=False, default_factory=list)
    vector: Optional[list[float]] = None

    def prepare(self, max_len: int) -> "Idea":
        self.raw = (self.raw or "").strip()
        self.usable = bool(self.raw) and len(self.raw) <= max_len
        if self.usable:
            self.norm = normalize(self.raw)
            self.stems = stem_set(self.raw)
        return self


@dataclass
class Verdict:
    row: int
    idea: str
    status: str                    # taken | planned | similar | free | skipped
    message: str                   # готовая человекочитаемая формулировка
    score: float = 0.0             # похожесть с найденным дублем (0..1)
    kind: str = ""                 # «по словам» / «по смыслу»
    match_row: Optional[int] = None
    match_text: str = ""
    published: str = ""            # где опубликован дубль (для 🔴)

    @property
    def label(self) -> str:
        return STATUS_LABEL.get(self.status, self.status)


def _trim(text: str, n: int = 90) -> str:
    t = re.sub(r"\s+", " ", str(text)).strip()
    return t[:n] + "…" if len(t) > n else t


def evaluate(idea: Idea, others: list[Idea],
             thresholds: Thresholds = DEFAULT_THRESHOLDS) -> Verdict:
    """Оценить одну идею на фоне остальных. Возвращает Verdict."""
    if not idea.raw:
        return Verdict(idea.row, "", "free", "")
    if not idea.usable:
        return Verdict(idea.row, idea.raw, "skipped",
                       STATUS_LABEL["skipped"] + " — слишком длинный текст")

    best_lex = (0.0, None)   # (score, Idea)
    best_sem = (0.0, None)
    for other in others:
        if other.row == idea.row or not other.usable:
            continue
        lex = lexical_similarity(idea.norm, idea.stems, other.norm, other.stems)
        if lex > best_lex[0]:
            best_lex = (lex, other)
        if idea.vector is not None and other.vector is not None:
            sem = cosine(idea.vector, other.vector)
            if sem > best_sem[0]:
                best_sem = (sem, other)

    lex_level = (2 if best_lex[0] >= thresholds.dup_limit
                 else 1 if best_lex[0] >= thresholds.sim_limit else 0)
    sem_level = (2 if best_sem[0] >= thresholds.sem_dup_limit
                 else 1 if best_sem[0] >= thresholds.sem_sim_limit else 0)
    level = max(lex_level, sem_level)

    if level == 0:
        return Verdict(idea.row, idea.raw, "free", STATUS_LABEL["free"])

    use_lex = lex_level >= sem_level
    score, match = best_lex if use_lex else best_sem
    kind = "по словам" if use_lex else "по смыслу"
    pct = round(score * 100)
    tail = (f" ({pct}%, {kind}) — строка {match.row}: {_trim(match.raw)}")

    common = dict(row=idea.row, idea=idea.raw, score=score, kind=kind,
                  match_row=match.row, match_text=match.raw)
    if level == 1:
        return Verdict(status="similar", message=STATUS_LABEL["similar"] + tail,
                       **common)
    if match.published:
        return Verdict(status="taken", published=match.published,
                       message=f"{STATUS_LABEL['taken']}, выложено "
                               f"{match.published}{tail}", **common)
    return Verdict(status="planned",
                   message=STATUS_LABEL["planned"] + ", но не выложено" + tail,
                   **common)


def run_dedup(ideas: list[Idea],
              thresholds: Thresholds = DEFAULT_THRESHOLDS) -> list[Verdict]:
    """Проверить все идеи. Векторы (если нужны) уже должны быть проставлены."""
    return [evaluate(idea, ideas, thresholds) for idea in ideas]


def summarize(verdicts: list[Verdict]) -> dict[str, int]:
    counts = {s: 0 for s in STATUS_ORDER}
    for v in verdicts:
        counts[v.status] = counts.get(v.status, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Чтение идей из «сетки» листа (grid — список строк-списков, как в loader)
# ---------------------------------------------------------------------------
def read_ideas_from_grid(grid: list[list[Any]], col_idea: int,
                         col_published: int, row_start: int,
                         thresholds: Thresholds = DEFAULT_THRESHOLDS
                         ) -> list[Idea]:
    """Собрать идеи из матрицы значений листа.

    col_idea / col_published — индексы столбцов (0-based). row_start — индекс
    первой строки данных (0-based). Пустые строки пропускаются, но нумерация
    строк Excel сохраняется (row = индекс + 1)."""
    out: list[Idea] = []
    for i in range(row_start, len(grid)):
        row = grid[i]
        raw = str(row[col_idea]).strip() if col_idea < len(row) and \
            row[col_idea] is not None else ""
        if not raw:
            continue
        pub = ""
        if 0 <= col_published < len(row) and row[col_published] is not None:
            pub = str(row[col_published]).strip()
        out.append(Idea(row=i + 1, raw=raw, published=pub)
                   .prepare(thresholds.max_idea_length))
    return out
