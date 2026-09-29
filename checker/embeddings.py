"""Смысловые эмбеддинги через Google Gemini (для проверки дублей по смыслу).

Использует тот же SDK google-genai и тот же ключ google_ai_api_key, что и
смысловая проверка постов (checker/ai_review.py). Сеть и пакет подгружаются
лениво, чтобы модуль импортировался даже без ключа/пакета — тогда работает
только лексическая проверка дублей.

Векторы возвращаются УЖЕ НОРМИРОВАННЫМИ (длина 1), поэтому косинус — это
обычное скалярное произведение (см. dedup.cosine).
"""
from __future__ import annotations

import math
import time
from typing import Optional

# Значения по умолчанию (перенесены из скрипта Apps Script).
DEFAULT_MODEL = "gemini-embedding-001"
DEFAULT_DIMS = 768
DEFAULT_BATCH = 100          # google-genai принимает список за один запрос
TASK_TYPE = "SEMANTIC_SIMILARITY"
_MAX_CHARS = 2000            # длинные тексты обрезаем (как в исходнике)


def _normalize(values: list[float]) -> list[float]:
    length = math.sqrt(sum(v * v for v in values))
    if length == 0:
        return list(values)
    return [v / length for v in values]


def _friendly_error(exc: Exception) -> str:
    s = str(exc).lower()
    if any(x in s for x in ("api_key", "api key", "invalid", "unauthenticated",
                            "permission", "401", "403")):
        return "Неверный ключ Google AI или нет доступа к Embeddings API."
    if any(x in s for x in ("quota", "resource_exhausted", "rate", "429")):
        return ("Превышен лимит запросов к Google AI. Подождите минуту и "
                "повторите — уже посчитанное не потеряется.")
    if any(x in s for x in ("not found", "not supported", "404")):
        return f"Модель эмбеддингов недоступна для этого ключа ({DEFAULT_MODEL})."
    if any(x in s for x in ("503", "overloaded", "unavailable", "high demand")):
        return "Google AI сейчас перегружен, попробуйте через минуту."
    if any(x in s for x in ("deadline", "timeout", "timed out")):
        return "Google AI не ответил вовремя. Попробуйте ещё раз."
    if any(x in s for x in ("connection", "network", "getaddrinfo", "ssl")):
        return "Нет связи с Google AI (проверьте интернет/доступность сервиса)."
    return "Не удалось получить эмбеддинги. Попробуйте ещё раз."


def _is_transient(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(x in s for x in ("503", "unavailable", "overloaded",
                                "high demand", "429", "resource_exhausted"))


def embed_texts(texts: list[str], api_key: str,
                model: str = DEFAULT_MODEL, dims: int = DEFAULT_DIMS,
                batch_size: int = DEFAULT_BATCH, pause: float = 0.0,
                progress_cb=None) -> dict:
    """Посчитать эмбеддинги для списка текстов.

    Возвращает {"ok": True, "vectors": [[...], ...]} (в порядке входа) либо
    {"ok": False, "error": "…"} с понятным русским текстом. Векторы нормированы.
    progress_cb(done, total) — для прогресс-бара.
    """
    if not texts:
        return {"ok": True, "vectors": []}
    if not api_key:
        return {"ok": False, "error": "Ключ Google AI не задан."}
    try:
        from google import genai
        from google.genai import types
    except Exception:  # noqa: BLE001
        return {"ok": False,
                "error": "Пакет google-genai не установлен на сервере."}

    try:
        client = genai.Client(api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _friendly_error(exc)}

    config = types.EmbedContentConfig(task_type=TASK_TYPE,
                                      output_dimensionality=dims)
    vectors: list[list[float]] = []
    total = len(texts)
    for start in range(0, total, batch_size):
        chunk = [str(t)[:_MAX_CHARS] for t in texts[start:start + batch_size]]
        try:
            resp = _embed_chunk(client, model, chunk, config)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": _friendly_error(exc)}
        for emb in resp.embeddings:
            vectors.append(_normalize(list(emb.values)))
        if progress_cb:
            progress_cb(min(start + batch_size, total), total)
        if pause and start + batch_size < total:
            time.sleep(pause)
    return {"ok": True, "vectors": vectors}


def _embed_chunk(client, model: str, chunk: list[str], config,
                 retries: int = 2, pause: float = 1.0):
    last: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return client.models.embed_content(
                model=model, contents=chunk, config=config)
        except Exception as exc:  # noqa: BLE001
            last = exc
            if _is_transient(exc) and attempt < retries:
                time.sleep(pause * (attempt + 1))
                continue
            raise
    raise last  # pragma: no cover


def test_connection(api_key: str, model: str = DEFAULT_MODEL,
                    dims: int = DEFAULT_DIMS) -> tuple[bool, str]:
    """Контрольный замер на типовых темах (как в исходном скрипте)."""
    probes = [
        "как правильно хранить металлопрокат",
        "как транспортировать и хранить металлопрокат зимой",
        "поздравление с днём народного единства",
    ]
    res = embed_texts(probes, api_key, model=model, dims=dims)
    if not res["ok"]:
        return False, res["error"]
    from .dedup import cosine
    v = res["vectors"]
    close = round(cosine(v[0], v[1]) * 100)
    far = round(cosine(v[0], v[2]) * 100)
    return True, (f"Связь есть. Похожие темы: {close}% (должно быть высоко), "
                  f"разные темы: {far}% (должно быть низко).")
