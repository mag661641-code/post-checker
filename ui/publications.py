"""Экран «Проверка публикаций»: онлайн-сверка опубликованных постов."""
from __future__ import annotations

import difflib

import pandas as pd
import streamlit as st

from checker import online_checks
from checker.models import Level, PostRecord
from ui import common as C

_RESULT_LABEL = {
    "ok": "✅ совпадает",
    "diff": "⚠️ текст отличается",
    "missing": "❌ пост не найден",
    "manual": "➖ проверить вручную",
}


def render() -> None:
    file_bytes = st.session_state.get("file_bytes")
    if not file_bytes:
        C.empty_no_file()
        return

    data = C.build_app_data(file_bytes)
    C.ensure_period(data)
    period = C.current_period()

    st.title("Проверка публикаций")
    st.caption("Онлайн-сверка опубликованных постов с Telegram и ВКонтакте. "
               "Идёт в интернет и занимает время. Работа зависит от площадок.")

    C.month_selector(data, key_prefix="pub")
    brand_filter = C.filters_bar(data, brand_only=True)

    vk_key = None
    try:
        vk_key = st.secrets.get("vk", {}).get("service_key")  # type: ignore
    except Exception:  # noqa: BLE001
        vk_key = None
    st.caption("Ключ ВКонтакте: " + ("задан" if vk_key else "не задан — "
               "проверяется только доступность страницы"))

    # посты «Выложено» за месяц выбранных брендов
    posts = []
    for p in data.posts:
        if not C.period_matches(p.date, period):
            continue
        if p.brand not in brand_filter["brands"]:
            continue
        if data.post_status.get((p.sheet, p.row), "") != "Выложено":
            continue
        posts.append(p)

    label = ("Проверить публикации за " + C.period_title(period)
             if period else "Проверить публикации за все месяцы")

    if "pub_stop" not in st.session_state:
        st.session_state["pub_stop"] = False

    col1, col2 = st.columns([3, 1])
    start = col1.button(f"{label} ({len(posts)} постов)", type="primary",
                        disabled=not posts, key="pub_start")
    if col2.button("Остановить", key="pub_stop_btn"):
        st.session_state["pub_stop"] = True

    if start:
        st.session_state["pub_stop"] = False
        _run(data, posts, vk_key)

    _show_results()


def _run(data: C.AppData, posts: list[PostRecord], vk_key) -> None:
    rules = data.cfg["rules"]
    tasks = [(p, s["link"]) for p in posts for s in p.socials if s.get("link")]
    total = len(tasks) or 1
    results = []
    with st.status("Проверяем публикации…", expanded=True) as status:
        for n, (post, url) in enumerate(tasks, 1):
            if st.session_state.get("pub_stop"):
                status.update(label="Остановлено пользователем.", state="error")
                break
            try:
                issues = online_checks.check_post_online(post, url, rules, vk_key)
            except Exception as e:  # noqa: BLE001
                issues = []
            results.append(_row(post, url, issues))
            status.update(label=f"Проверено {n} из {total}…")
        else:
            status.update(label=f"Готово. Проверено {total}.", state="complete")
    st.session_state["pub_results"] = results


def _row(post: PostRecord, url: str, issues) -> dict:
    from checker import normalize as N
    result = "ok"
    detail = None
    for i in issues:
        if i.code.endswith("deleted"):
            result = "missing"
        elif i.code.endswith("diff"):
            result = "diff"
            detail = i.extra
        elif i.code in ("online_unreachable", "online_blocked",
                        "online_tg_unparsed"):
            result = "manual"
    return {
        "Дата": C.fmt_date_short(post.date),
        "Бренд": post.brand,
        "Площадка": {"t.me": "Telegram", "vk.com": "VK", "ok.ru": "OK",
                     "max.ru": "Max", "dzen.ru": "Дзен"}.get(
                         N.link_domain(url), N.link_domain(url)),
        "Ссылка": url,
        "Результат": _RESULT_LABEL[result],
        "_detail": detail,
    }


def _show_results() -> None:
    results = st.session_state.get("pub_results")
    if not results:
        st.info("Нажмите кнопку, чтобы проверить публикации.")
        return
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "_detail"}
                       for r in results])
    st.dataframe(df, use_container_width=True, hide_index=True,
                 column_config={"Ссылка": st.column_config.LinkColumn("Ссылка")})

    diffs = [r for r in results if r["_detail"]]
    if diffs:
        st.subheader("Расхождения текста")
        for n, r in enumerate(diffs):
            if st.button(f"{r['Бренд']} · {r['Дата']} · показать различия",
                         key=f"diff_{n}"):
                _diff_dialog(r)


@st.dialog("Сравнение текста")
def _diff_dialog(r: dict) -> None:
    detail = r["_detail"] or {}
    exp = (detail.get("expected") or "").split("\n")
    pub = (detail.get("published") or "").split("\n")
    diff = difflib.unified_diff(exp, pub, "В таблице", "Опубликовано", lineterm="")
    st.code("\n".join(diff) or "нет различий", language="diff")
