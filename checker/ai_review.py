"""Смысловая проверка текста поста нейросетью (Google Gemini).

Модуль не зависит от Streamlit — его можно тестировать отдельно. Сеть и SDK
`google-genai` подгружаются лениво, внутри функций, чтобы модуль импортировался
даже без установленного пакета/ключа.

Главный принцип: нейросеть НЕ переписывает текст и НЕ меняет факты. Она только
возвращает замечания. Всё, что похоже на выдумку (числа, которых нет в тексте),
отбрасывается уже на нашей стороне — см. validate_issues().
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

# значения по умолчанию для раздела rules["ai"]
DEFAULT_AI: dict[str, Any] = {
    "model": "gemini-3.6-flash",
    "check_tone": True,
    "check_structure": True,
    "check_quality": True,
    "level": "advice",          # уровень по умолчанию для замечаний ИИ
    "max_issues": 5,            # максимум замечаний на пост
    "pause_seconds": 1.0,       # пауза между запросами (для массовой проверки)
}

_CATEGORIES = {"tone", "structure", "quality", "fact", "promise"}
# факты и противоречия — предупреждение, остальное — по настройке уровня
_WARN_CATEGORIES = {"fact", "promise"}

# коды замечаний ИИ (по ним отличаем источник и значок 🤖)
CODE_BY_CATEGORY = {
    "tone": "ai_tone", "structure": "ai_structure", "quality": "ai_quality",
    "fact": "ai_fact", "promise": "ai_promise",
}
_NUM_RE = re.compile(r"\d+(?:[.,]\d+)?")


def ai_settings(rules: dict) -> dict[str, Any]:
    """Настройки ИИ с подстановкой значений по умолчанию."""
    out = dict(DEFAULT_AI)
    out.update(rules.get("ai", {}) or {})
    return out


# ---------------------------------------------------------------------------
# Построение запроса
# ---------------------------------------------------------------------------
def build_prompt(brand: str, post_type: str, date: str, text: str,
                 tone: str, avoid: str, structure: str,
                 cats: list[str], max_issues: int) -> str:
    parts = [
        "Ты — редактор постов металлоторговой компании. Ты ПРОВЕРЯЕШЬ текст "
        "поста и предлагаешь точечные правки формулировок. "
        "Ты правишь ТОЛЬКО стиль и подачу (тон, гладкость, повторы, ясность), "
        "и НИКОГДА не меняешь факты: числа, марки стали, ГОСТы, размеры, "
        "количества, сроки, даты, цены, телефоны, адреса сайтов, названия. "
        "Ты не переписываешь пост целиком и не сочиняешь новых фактов.",
        "",
        f"Бренд: {brand or '—'}",
        f"Тип поста: {post_type or '—'}",
        f"Дата: {date or '—'}",
        "Текст поста:",
        '"""',
        text or "",
        '"""',
        "",
    ]
    checks = []
    if "tone" in cats and tone.strip():
        parts += ["Тон бренда (эталон):", tone.strip(), ""]
        checks.append("тон: соответствует ли текст эталонному тону бренда")
    if "tone" in cats and avoid.strip():
        parts += ["Чего избегать для этого бренда:", avoid.strip(), ""]
    if "structure" in cats and structure.strip():
        parts += ["Из чего должен состоять такой пост:", structure.strip(), ""]
        checks.append("структура: все ли нужные блоки на месте")
    if "quality" in cats:
        checks.append("качество текста: сухость, нескладность, противоречия, "
                      "повторы, сомнительные числа, рискованные обещания")
    parts += [
        "Проверь: " + "; ".join(checks) + ".",
        "",
        "Как оформлять каждое замечание:",
        "- fragment — точная дословная подстрока из текста поста (скопируй "
        "буква в букву, вместе с знаками), к которой относится правка; если "
        "замечание про весь пост, оставь fragment пустым;",
        "- suggestions — 1–3 варианта, как ПЕРЕПИСАТЬ этот фрагмент лучше по "
        "стилю. В вариантах сохраняй ВСЕ факты фрагмента без изменений (те же "
        "числа, марки, ГОСТы, размеры, сроки, цены, контакты, ссылки). Не "
        "добавляй новых цифр и фактов, которых нет во фрагменте;",
        "- если у фрагмента возможны РАЗНЫЕ смыслы (например, действие делает "
        "менеджер или сам клиент), дай по варианту на каждый смысл и заполни "
        "поле when («Если …»); иначе when оставь пустым;",
        "",
        "Особые случаи (НЕ предлагай замену текста, suggestions оставь пустым "
        "массивом [] ):",
        "- category = fact — сомнительное или требующее проверки число/факт: "
        "напиши это ВОПРОСОМ человеку в why, ты не знаешь реального положения "
        "дел;",
        "- category = promise — рискованное обещание (срок, гарантия): тоже "
        "вопрос на проверку, без готовой замены.",
        "",
        f"Дай не более {max_issues} самых важных замечаний.",
        "",
        "Ответ верни строго в JSON по схеме. issues — массив объектов с полями "
        "category, level, title, why, fragment, suggestions. "
        "category ∈ {tone, structure, quality, fact, promise}; "
        "level ∈ {advice, warning}. suggestions — массив объектов {when, text}.",
    ]
    return "\n".join(parts)


def _schema(genai_types):
    S = genai_types.Schema
    T = genai_types.Type
    suggestion = S(type=T.OBJECT, properties={
        "when": S(type=T.STRING),
        "text": S(type=T.STRING),
    }, required=["when", "text"])
    issue = S(type=T.OBJECT, properties={
        "category": S(type=T.STRING),
        "level": S(type=T.STRING),
        "title": S(type=T.STRING),
        "why": S(type=T.STRING),
        "fragment": S(type=T.STRING),
        "suggestions": S(type=T.ARRAY, items=suggestion),
    }, required=["category", "level", "title", "why", "fragment", "suggestions"])
    return S(type=T.OBJECT, properties={"issues": S(type=T.ARRAY, items=issue)},
             required=["issues"])


# ---------------------------------------------------------------------------
# Защита от выдумок (чистая логика, тестируется без сети)
# ---------------------------------------------------------------------------
def _numbers(s: str) -> set[str]:
    return {m.replace(",", ".") for m in _NUM_RE.findall(s or "")}


def _clean_option(opt: Any, text_nums: set[str], frag_nums: set[str],
                  fragment: str, limit: int = 400) -> Optional[dict]:
    """Проверить один вариант замены. Отбрасываем варианты с НОВЫМИ числами
    (которых нет в тексте/фрагменте) и пустые/совпадающие с оригиналом."""
    if not isinstance(opt, dict):
        return None
    when = re.sub(r"\s+", " ", str(opt.get("when", "")).strip())
    txt = re.sub(r"\s+", " ", str(opt.get("text", "")).strip())
    if not txt or txt == re.sub(r"\s+", " ", fragment.strip()):
        return None
    if len(txt) > limit:
        txt = txt[:limit].rstrip() + "…"
    # анти-выдумка: в замене не должно быть чисел, которых нет в оригинале
    if _numbers(txt) - (text_nums | frag_nums):
        return None
    return {"when": when, "text": txt}


def validate_issues(raw_issues: list[dict], text: str,
                    settings: dict) -> list[dict]:
    """Отфильтровать и почистить замечания от нейросети.

    Формат замечания на выходе:
        category, level, title, why, fragment, options[{when, text}]

    - только включённые категории и корректные поля;
    - fragment должен быть дословной подстрокой текста, иначе он обнуляется;
    - выбрасываем замечания, где в title/why есть числа, которых нет в тексте
      (числа во фрагменте допускаются);
    - варианты замены (options) только для стилевых категорий и при валидном
      фрагменте; варианты с новыми числами отбрасываются;
    - для fact/promise замен не предлагаем — только вопрос-предупреждение;
    - ограничиваем количество.
    """
    cats_on = set()
    if settings.get("check_tone", True):
        cats_on.add("tone")
    if settings.get("check_structure", True):
        cats_on.add("structure")
    if settings.get("check_quality", True):
        cats_on |= {"quality", "fact", "promise"}
    text_nums = _numbers(text)
    default_level = settings.get("level", "advice")
    max_issues = int(settings.get("max_issues", 5) or 5)

    out: list[dict] = []
    for it in raw_issues or []:
        if not isinstance(it, dict):
            continue
        cat = str(it.get("category", "")).strip().lower()
        if cat not in _CATEGORIES or cat not in cats_on:
            continue
        title = str(it.get("title", "")).strip()
        why = str(it.get("why", "")).strip()
        if not title:
            continue
        fragment = str(it.get("fragment", "")).strip()
        if fragment and fragment not in (text or ""):
            fragment = ""  # не смогли привязать к тексту — не подсвечиваем
        frag_nums = _numbers(fragment)
        # анти-выдумка: числа в заголовке/пояснении должны быть из текста
        if (_numbers(title) | _numbers(why)) - (text_nums | frag_nums):
            continue
        # варианты замены — только для стилевых категорий и при якоре
        options: list[dict] = []
        if cat not in _WARN_CATEGORIES and fragment:
            for o in (it.get("suggestions") or it.get("options") or []):
                cleaned = _clean_option(o, text_nums, frag_nums, fragment)
                if cleaned:
                    options.append(cleaned)
                if len(options) >= 3:
                    break
        level = str(it.get("level", "")).strip().lower()
        if cat in _WARN_CATEGORIES:
            level = "warning"
        elif level not in ("advice", "warning"):
            level = default_level
        out.append({"category": cat, "level": level, "title": title,
                    "why": why, "fragment": fragment, "options": options})
        if len(out) >= max_issues:
            break
    return out


# ---------------------------------------------------------------------------
# Вызов нейросети
# ---------------------------------------------------------------------------
def _friendly_error(exc: Exception) -> str:
    s = str(exc).lower()
    if "api_key" in s or "api key" in s or "invalid" in s or "unauthenticated" \
            in s or "permission" in s or "401" in s or "403" in s:
        return "Неверный ключ Google AI или нет доступа."
    if "503" in s or "high demand" in s or "overloaded" in s or \
            "try again later" in s:
        return "Google AI сейчас перегружен, попробуйте через минуту."
    if "quota" in s or "resource_exhausted" in s or "rate" in s or "429" in s:
        return "Превышен лимит запросов к Google AI. Попробуйте позже."
    if "not found" in s or "not supported" in s or "404" in s:
        return ("Выбранная модель недоступна для этого ключа. Выберите другую "
                "модель в настройках (например, gemini-2.5-flash-lite).")
    if "deadline" in s or "timeout" in s or "timed out" in s:
        return "Google AI не ответил вовремя. Попробуйте ещё раз."
    if "connection" in s or "network" in s or "unavailable" in s or \
            "getaddrinfo" in s or "ssl" in s:
        return "Нет связи с Google AI (проверьте интернет/доступность сервиса)."
    return "Проверка нейросетью не выполнена. Попробуйте ещё раз."


def _is_transient(exc: Exception) -> bool:
    s = str(exc).lower()
    return ("503" in s or "unavailable" in s or "high demand" in s
            or "overloaded" in s or "429" in s or "resource_exhausted" in s)


def _generate(client, model: str, contents, config=None,
              retries: int = 2, pause: float = 1.0):
    """Вызов модели с повтором при временных ошибках (503/лимит)."""
    last: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return client.models.generate_content(
                model=model, contents=contents, config=config)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if _is_transient(exc) and attempt < retries:
                time.sleep(pause * (attempt + 1))
                continue
            raise
    raise last  # pragma: no cover


def review(text: str, brand: str, post_type: str, date: str,
           tone: str, avoid: str, structure: str,
           settings: dict, api_key: str) -> dict[str, Any]:
    """Проверить один пост. Вернуть {"ok": True, "issues": [...]} либо
    {"ok": False, "error": "…"} с понятным русским текстом."""
    if not (text or "").strip():
        return {"ok": True, "issues": []}
    if not api_key:
        return {"ok": False, "error": "Ключ Google AI не задан."}
    cats = []
    if settings.get("check_tone", True):
        cats.append("tone")
    if settings.get("check_structure", True):
        cats.append("structure")
    if settings.get("check_quality", True):
        cats.append("quality")
    if not cats:
        return {"ok": True, "issues": []}

    try:
        from google import genai
        from google.genai import types
    except Exception:  # noqa: BLE001
        return {"ok": False,
                "error": "Пакет google-genai не установлен на сервере."}

    prompt = build_prompt(brand, post_type, date, text, tone, avoid, structure,
                          cats, int(settings.get("max_issues", 5) or 5))
    try:
        client = genai.Client(api_key=api_key)
        resp = _generate(
            client, settings.get("model") or DEFAULT_AI["model"], prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_schema(types),
                temperature=0.2,
            ),
            pause=float(settings.get("pause_seconds", 1.0) or 1.0),
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _friendly_error(exc)}

    payload = getattr(resp, "text", None)
    if not payload:
        return {"ok": False, "error": "Нейросеть не вернула ответ."}
    try:
        data = json.loads(payload)
        raw = data.get("issues", []) if isinstance(data, dict) else []
    except Exception:  # noqa: BLE001
        return {"ok": False,
                "error": "Нейросеть вернула ответ в неожиданном формате, "
                         "попробуйте ещё раз."}
    return {"ok": True, "issues": validate_issues(raw, text, settings)}


def test_connection(api_key: str, model: str) -> tuple[bool, str]:
    """Короткий тестовый запрос. Возвращает (успех, русское сообщение)."""
    if not api_key:
        return False, "Ключ не задан."
    try:
        from google import genai
    except Exception:  # noqa: BLE001
        return False, "Пакет google-genai не установлен на сервере."
    try:
        client = genai.Client(api_key=api_key)
        resp = _generate(client, model or DEFAULT_AI["model"],
                         "Ответь одним словом: ок")
        txt = (getattr(resp, "text", "") or "").strip()
        return True, f"Связь с Google AI есть. Ответ: «{txt[:40]}»."
    except Exception as exc:  # noqa: BLE001
        # для кнопки диагностики показываем и техническую деталь ошибки
        msg = _friendly_error(exc)
        detail = " ".join(str(exc).split())[:300]
        if detail and detail.lower() not in msg.lower():
            msg += f" Детали: {detail}"
        return False, msg
