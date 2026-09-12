"""Экран «Проверка публикаций»: онлайн-сверка опубликованных постов.

Проверяет все площадки (Telegram, ВКонтакте, Одноклассники, Max, WhatsApp,
Дзен) и честно показывает, что именно проверено: текст сверился, страница лишь
открылась, пост не найден и т.д. Два вида результата — «По постам» и «Все
ссылки».
"""
from __future__ import annotations

import difflib
import re
import time

import pandas as pd
import streamlit as st

from checker import online_checks, config_mod
from checker import normalize as N
from checker.models import PostRecord
from ui import common as C

# порядок и заголовки столбцов-площадок в виде «По постам»
COLS = ["Telegram", "ВКонтакте", "Одноклассники", "Max", "WhatsApp", "Дзен"]
COL_HEADER = {"Одноклассники": "ОК"}

# как названия ожидаемых площадок из настроек ложатся на столбцы
EXPECTED_TO_COL = {
    "Telegram": "Telegram", "Telegram (сотрудники)": "Telegram",
    "ВКонтакте": "ВКонтакте", "Одноклассники": "Одноклассники",
    "Max": "Max", "WhatsApp": "WhatsApp", "Дзен": "Дзен",
}

_LEGEND = ("✅ текст совпадает · ⚠️ отличается · 🔗 открывается, текст не сверялся"
           " · ❌ не найден · 🔒 проверьте вручную · ➖ нет ссылки"
           " · 👁 проверено вручную")


def render() -> None:
    file_bytes = st.session_state.get("file_bytes")
    if not file_bytes:
        C.empty_no_file()
        return

    data = C.build_app_data(file_bytes)
    C.ensure_period(data)
    period = C.current_period()
    rules = data.cfg["rules"]
    brands = data.cfg["brands"]

    st.title("Проверка публикаций")
    st.caption("Онлайн-сверка опубликованных постов с площадками. Идёт в интернет "
               "и занимает время. Результат зависит от того, что площадка отдаёт "
               "роботам.")

    C.period_selector(data, key_prefix="pub")

    brand_filter = C.filters_bar(data, brand_only=True)
    chosen_platforms = st.pills("Площадка", COLS, selection_mode="multi",
                                default=COLS, key="pub_platforms") or COLS

    vk_key = _vk_key()

    # --- посты «Выложено» за месяц ---
    month_posts = C.posts_in_period(data, period)
    posted_all = [p for p in month_posts
                  if data.post_status.get((p.sheet, p.row), "") == "Выложено"]
    posted = [p for p in posted_all if p.brand in brand_filter["brands"]]

    tasks = _tasks(posted, chosen_platforms)

    # --- строка с количеством за месяц ---
    if not month_posts:
        st.caption(f"За {C.period_title(period)} постов в таблице пока нет")
    else:
        st.caption(f"За {C.period_title(period)}: {C.plural_posts(len(month_posts))}, "
                   f"выложено {len(posted_all)}, "
                   f"ссылок для проверки {C.plural_links(len(tasks))}")

    # --- кнопки запуска/остановки (остановка видна только во время проверки) ---
    running = st.session_state.get("pub_running", False)
    label = (f"Проверить публикации за {C.period_title(period)} · "
             f"{C.plural_posts(len(posted))}, {C.plural_links(len(tasks))}")
    brow = st.columns([5, 2, 5], vertical_alignment="bottom")
    start = brow[0].button(label, type="primary", disabled=not tasks or running,
                           key="pub_start", use_container_width=True)
    if running and brow[1].button("⏹ Остановить", key="pub_stop_btn",
                                  use_container_width=True):
        st.session_state["pub_stop"] = True

    if start:
        st.session_state["pub_running"] = True
        st.session_state["pub_stop"] = False
        st.rerun()

    if running:
        _run(data, tasks, vk_key, brands)
        st.session_state["pub_running"] = False
        st.rerun()

    _show_results(data, posted, chosen_platforms, vk_key)


# ---------------------------------------------------------------------------
# Сбор задач и запуск
# ---------------------------------------------------------------------------
def _vk_key():
    try:
        return st.secrets.get("vk", {}).get("service_key")  # type: ignore
    except Exception:  # noqa: BLE001
        return None


def _tasks(posted: list[PostRecord], chosen_platforms: list[str]) -> list[tuple]:
    tasks = []
    for p in posted:
        for s in p.socials:
            link = s.get("link")
            if not link:
                continue
            if online_checks.detect_platform(link) not in chosen_platforms:
                continue
            tasks.append((p, link))
    return tasks


def _run(data: C.AppData, tasks: list[tuple], vk_key, brands: dict) -> None:
    rules = data.cfg["rules"]
    pause = rules.get("online", {}).get("pause_seconds", 1.0)
    total = len(tasks) or 1
    results = []
    with st.status("Проверяем публикации…", expanded=True) as status:
        stopped = False
        for n, (post, url) in enumerate(tasks, 1):
            if st.session_state.get("pub_stop"):
                status.update(label="Остановлено пользователем.", state="error")
                stopped = True
                break
            try:
                res = online_checks.check_link(post, url, rules, vk_key, brands)
            except Exception as e:  # noqa: BLE001
                res = online_checks.LinkResult(
                    online_checks.detect_platform(url), url, "blocked",
                    note=f"ошибка проверки: {e}")
            results.append(_serialize(post, url, res))
            status.update(label=f"Проверено {n} из {total}…")
            if n < len(tasks):
                time.sleep(pause)
        if not stopped:
            status.update(label=f"Готово. Проверено {total}.", state="complete")
    st.session_state["pub_results"] = results


def _serialize(post: PostRecord, url: str, res: online_checks.LinkResult) -> dict:
    return {
        "sheet": post.sheet, "row": post.row, "brand": post.brand,
        "date": C.fmt_date_compact(post.date),
        "post_preview": _preview(post.text),
        "platform": res.platform, "url": url, "channel": res.channel,
        "status": res.status, "note": res.note,
        "published": res.published, "expected": res.expected,
    }


def _preview(text: str, limit: int = 40) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t:
        return "(без текста)"
    return t[:limit] + ("…" if len(t) > limit else "")


# ---------------------------------------------------------------------------
# Ожидаемые площадки поста
# ---------------------------------------------------------------------------
def _expected_cols(post: PostRecord, rules: dict) -> set[str]:
    cfg = rules.get("expected_platforms", {})
    default = cfg.get("default", [])
    by_bt = cfg.get("by_brand_type", {})
    canon, _ = N.canonical_post_type(post.post_type,
                                     rules.get("post_type_canonical", {}))
    expected = (by_bt.get(f"{post.brand}|{canon}")
                or by_bt.get(f"*|{canon}") or default)
    cols = set()
    for e in expected:
        c = EXPECTED_TO_COL.get(e)
        if c:
            cols.add(c)
    return cols


def _eff_status(r: dict) -> str:
    if config_mod.is_manual(r["url"]):
        return "manual"
    return r["status"]


# ---------------------------------------------------------------------------
# Показ результатов
# ---------------------------------------------------------------------------
def _show_results(data: C.AppData, posted: list[PostRecord],
                  chosen_platforms: list[str], vk_key) -> None:
    results = st.session_state.get("pub_results")
    if not results:
        st.info("Нажмите кнопку, чтобы проверить публикации.")
        return

    rules = data.cfg["rules"]
    res_by_post: dict[tuple, list[dict]] = {}
    for r in results:
        res_by_post.setdefault((r["sheet"], r["row"]), []).append(r)

    # матрица «пост × площадка» (только выбранные площадки, для показанного месяца)
    matrix = []
    for p in posted:
        expected = _expected_cols(p, rules)
        cells = {c: [] for c in COLS}
        for r in res_by_post.get((p.sheet, p.row), []):
            if r["platform"] in cells:
                cells[r["platform"]].append(r)
        matrix.append({"post": p, "expected": expected, "cells": cells})

    # ограничения площадок — только для тех, что есть в результатах
    present = {r["platform"] for r in results}
    notes = []
    if "ВКонтакте" in present and not vk_key:
        notes.append("ВКонтакте: ключ не задан, текст не сверяется")
    if "WhatsApp" in present:
        notes.append("WhatsApp: текст постов автоматически не проверяется")
    if notes:
        st.caption(" · ".join(notes))

    st.markdown(_summary_line(matrix, chosen_platforms))

    view = st.segmented_control("Вид результата", ["По постам", "Все ссылки"],
                                default="По постам", key="pub_view",
                                label_visibility="collapsed")
    if view == "Все ссылки":
        _view_all_links(results)
    else:
        _view_by_post(matrix, chosen_platforms)

    st.caption(_LEGEND)


def _summary_line(matrix: list[dict], chosen_platforms: list[str]) -> str:
    buckets = {"ok": 0, "warn": 0, "link": 0, "missing": 0, "blocked": 0,
               "nolink": 0, "manual": 0}
    group = {"ok": "ok", "diff": "warn", "chat": "warn", "foreign": "warn",
             "link": "link", "missing": "missing", "blocked": "blocked",
             "manual": "manual"}
    for row in matrix:
        for col in COLS:
            if col not in chosen_platforms:
                continue
            res = row["cells"][col]
            if res:
                for r in res:
                    buckets[group.get(_eff_status(r), "warn")] += 1
            elif col in row["expected"]:
                buckets["nolink"] += 1
    line = (f"✅ {buckets['ok']} · ⚠️ {buckets['warn']} · 🔗 {buckets['link']} · "
            f"❌ {buckets['missing']} · 🔒 {buckets['blocked']} · ➖ {buckets['nolink']}")
    if buckets["manual"]:
        line += f" · 👁 {buckets['manual']}"
    return line


def _cell_text(row: dict, col: str) -> str:
    res = row["cells"][col]
    if res:
        return " ".join(online_checks.STATUS_ICON[_eff_status(r)] for r in res)
    if col in row["expected"]:
        return "➖"
    return ""


def _view_by_post(matrix: list[dict], chosen_platforms: list[str]) -> None:
    rows = []
    for row in matrix:
        p = row["post"]
        rec = {"Дата": p.date and C.fmt_date_compact(p.date) or "без даты",
               "Бренд": p.brand, "Пост": _preview(p.text, 45)}
        for col in COLS:
            header = COL_HEADER.get(col, col)
            rec[header] = _cell_text(row, col) if col in chosen_platforms else ""
        rows.append(rec)
    df = pd.DataFrame(rows)
    event = st.dataframe(
        df, use_container_width=True, hide_index=True,
        on_select="rerun", selection_mode="single-row", height=430,
        column_config={"Пост": st.column_config.TextColumn(width="large")})
    sel = event.selection.rows if event and event.selection else []
    if not sel or sel[0] >= len(matrix):
        st.caption("Выберите пост в таблице, чтобы увидеть подробности по ссылкам.")
        return
    _post_detail(matrix[sel[0]])


def _post_detail(row: dict) -> None:
    p = row["post"]
    st.markdown(f"**{p.brand} · {p.date and C.fmt_date_compact(p.date) or 'без даты'} "
                f"· {_preview(p.text, 60)}**")
    any_line = False
    for col in COLS:
        for i, r in enumerate(row["cells"][col]):
            any_line = True
            _detail_line(r, key=f"d_{p.sheet}_{p.row}_{col}_{i}")
        if not row["cells"][col] and col in row["expected"]:
            any_line = True
            _nolink_line(p, col)
    if not any_line:
        st.caption("По этому посту нет проверенных ссылок.")


def _detail_line(r: dict, key: str) -> None:
    eff = _eff_status(r)
    icon = online_checks.STATUS_ICON[eff]
    text = online_checks.STATUS_TEXT[eff]
    note = f" — {r['note']}" if r.get("note") else ""
    ch = f" ({r['channel']})" if r.get("channel") else ""
    cols = st.columns([7, 2, 2], vertical_alignment="center")
    with cols[0]:
        st.markdown(f"{icon} **{r['platform']}{ch}**: {text}{note}")
        st.caption(r["url"])
    if r["status"] == "diff":
        if cols[1].button("Показать разницу", key=f"{key}_diff",
                          use_container_width=True):
            _diff_dialog(r)
    # ручная отметка для 🔗 / 🔒 (и возможность отменить уже поставленную)
    if r["status"] in ("link", "blocked") or eff == "manual":
        _manual_button(r["url"], cols[2], key=f"{key}_man")


def _nolink_line(p: PostRecord, col: str) -> None:
    synthetic = f"{p.sheet}:{p.row}:{col}"
    eff = "manual" if config_mod.is_manual(synthetic) else "no_link"
    icon = online_checks.STATUS_ICON[eff]
    text = online_checks.STATUS_TEXT[eff]
    cols = st.columns([7, 2, 2], vertical_alignment="center")
    cols[0].markdown(f"{icon} **{col}**: {text}")
    _manual_button(synthetic, cols[2], key=f"nl_{p.sheet}_{p.row}_{col}")


def _manual_button(url_or_key: str, col, key: str) -> None:
    if config_mod.is_manual(url_or_key):
        added = config_mod.manual_added(url_or_key)
        col.caption(f"👁 {added}")
        if col.button("Отменить отметку", key=f"{key}_off",
                      use_container_width=True):
            config_mod.remove_manual(url_or_key)
            C.persist_all()
            st.rerun()
    else:
        if col.button("Отметить: проверено вручную", key=f"{key}_on",
                      type="tertiary", use_container_width=True):
            config_mod.add_manual(url_or_key)
            C.persist_all()
            st.rerun()


def _view_all_links(results: list[dict]) -> None:
    rows = []
    for r in results:
        eff = _eff_status(r)
        rows.append({
            "Дата": r["date"], "Бренд": r["brand"], "Площадка": r["platform"],
            "Ссылка": r["url"],
            "Результат": f"{online_checks.STATUS_ICON[eff]} "
                         f"{online_checks.STATUS_TEXT[eff]}",
        })
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True, height=430,
                 column_config={"Ссылка": st.column_config.LinkColumn("Ссылка")})

    diffs = [r for r in results if r["status"] == "diff"]
    if diffs:
        st.markdown("**Расхождения текста**")
        for n, r in enumerate(diffs):
            if st.button(f"{r['brand']} · {r['date']} · {r['platform']} — "
                         f"показать различия", key=f"alldiff_{n}"):
                _diff_dialog(r)


@st.dialog("Сравнение текста")
def _diff_dialog(r: dict) -> None:
    exp = (r.get("expected") or "").split("\n")
    pub = (r.get("published") or "").split("\n")
    diff = difflib.unified_diff(exp, pub, "В таблице", "Опубликовано", lineterm="")
    st.code("\n".join(diff) or "нет различий", language="diff")
