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
        "поста и даёшь замечания. Ты НИКОГДА не переписываешь текст целиком и "
        "не выдаёшь новую редакцию поста. Ты не придумываешь и не меняешь факты: "
        "числа, марки стали, ГОСТы, размеры, сроки, цены, телефоны, адреса сайтов.",
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
        "Жёсткие ограничения:",
        "- не предлагай менять числа, марки стали, ГОСТы, размеры, сроки, цены, "
        "контакты;",
        "- про сомнительные числа и обещания пиши ВОПРОСОМ на проверку человеку "
        "(ты не знаешь реального положения дел), а не как утверждение об ошибке;",
        "- в what_to_do не давай переписанный текст; допустим один короткий "
        "пример формулировки с пометкой «например», не длиннее одного предложения;",
        f"- не более {max_issues} самых важных замечаний.",
        "",
        "Ответ верни строго в JSON по схеме (issues — массив объектов с полями "
        "category, level, title, why, what_to_do, quote). "
        "category ∈ {tone, structure, quality, fact, promise}; "
        "level ∈ {advice, warning}. quote — короткая дословная цитата из поста, "
        "к которой относится замечание (или пустая строка).",
    ]
    return "\n".join(parts)


def _schema(genai_types):
    S = genai_types.Schema
    T = genai_types.Type
    issue = S(type=T.OBJECT, properties={
        "category": S(type=T.STRING),
        "level": S(type=T.STRING),
        "title": S(type=T.STRING),
        "why": S(type=T.STRING),
        "what_to_do": S(type=T.STRING),
        "quote": S(type=T.STRING),
    }, required=["category", "level", "title", "why", "what_to_do", "quote"])
    return S(type=T.OBJECT, properties={"issues": S(type=T.ARRAY, items=issue)},
             required=["issues"])


# ---------------------------------------------------------------------------
# Защита от выдумок (чистая логика, тестируется без сети)
# ---------------------------------------------------------------------------
def _numbers(s: str) -> set[str]:
    return {m.replace(",", ".") for m in _NUM_RE.findall(s or "")}


def _first_sentence(s: str, limit: int = 300) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    if len(s) <= limit:
        return s
    m = re.search(r"[.!?]", s[:limit])
    if m:
        return s[:m.end()].strip()
    return s[:limit].rstrip() + "…"


def validate_issues(raw_issues: list[dict], text: str,
                    settings: dict) -> list[dict]:
    """Отфильтровать и почистить замечания от нейросети.

    - только включённые категории и корректные поля;
    - выбрасываем замечания, где в title/why/what_to_do есть числа, которых нет
      в тексте поста (числа внутри quote допускаются);
    - what_to_do обрезаем до одного предложения / 300 символов;
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
        what = _first_sentence(str(it.get("what_to_do", "")))
        quote = str(it.get("quote", "")).strip()
        if not title:
            continue
        # анти-выдумка: числа вне цитаты должны быть из текста поста
        allowed = text_nums | _numbers(quote)
        extra_nums = (_numbers(title) | _numbers(why) | _numbers(what)) - allowed
        if extra_nums:
            continue
        level = str(it.get("level", "")).strip().lower()
        if cat in _WARN_CATEGORIES:
            level = "warning"
        elif level not in ("advice", "warning"):
            level = default_level
        out.append({"category": cat, "level": level, "title": title,
                    "why": why, "what_to_do": what, "quote": quote})
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
        resp = client.models.generate_content(
            model=settings.get("model") or DEFAULT_AI["model"],
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_schema(types),
                temperature=0.2,
            ),
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
        resp = client.models.generate_content(
            model=model or DEFAULT_AI["model"], contents="Ответь одним словом: ок")
        txt = (getattr(resp, "text", "") or "").strip()
        return True, f"Связь с Google AI есть. Ответ: «{txt[:40]}»."
    except Exception as exc:  # noqa: BLE001
        # для кнопки диагностики показываем и техническую деталь ошибки
        msg = _friendly_error(exc)
        detail = " ".join(str(exc).split())[:300]
        if detail and detail.lower() not in msg.lower():
            msg += f" Детали: {detail}"
        return False, msg
