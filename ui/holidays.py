"""Экран «Обязательные праздники»: сверка контент-плана с праздниками.

Оформление и логика как раньше. Добавлена только синхронизация выбранного
месяца с экраном «Проверка постов» и пояснительные подсказки.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from checker import holidays_mod
from checker.normalize import canonical_post_type
from ui import common as C

_MONTH_NAMES = [C.MONTHS_NOM[i] for i in range(1, 13)]


def render() -> None:
    file_bytes = st.session_state.get("file_bytes")
    if not file_bytes:
        C.empty_no_file()
        return

    data = C.build_app_data(file_bytes)
    brands = data.cfg["brands"]
    rules = data.cfg["rules"]

    st.title("Обязательные праздники")

    # --- единый выбор месяца и года (общий со всеми экранами) ---
    C.ensure_period(data)
    C.period_selector(data, key_prefix="hol")
    period = C.current_period()
    today = C.moscow_today()
    if isinstance(period, tuple):
        year, month = period
    else:
        year, month = today.year, today.month

    # есть ли вообще посты за этот месяц
    has_posts = any(p.date and (p.date.year, p.date.month) == (int(year), month)
                    for p in data.posts)
    if not has_posts:
        st.info(f"За {C.fmt_month_lower(int(year), month)} постов в файле пока "
                f"нет, поэтому у всех брендов ❌.")

    cal = holidays_mod.build_holiday_calendar(data.wb.holidays_raw, int(year))
    window = rules.get("thresholds", {}).get("holiday_window_days", 3)
    holiday_types = {"праздник", "поздравление"}

    rows = []
    for h in cal:
        if h["date"] is None or h["date"].month != month:
            continue
        row = {"Дата": h["date"].strftime("%d.%m.%Y"), "Праздник": h["name"],
               "Тип": h["type"]}
        targets = [h["corp_brand"]] if h["corp_brand"] else list(brands.keys())
        for code in brands.keys():
            if code not in targets:
                row[code] = "—"
                continue
            found = False
            for post in data.wb.posts.get(code, []):
                if not post.date:
                    continue
                canon, _ = canonical_post_type(post.post_type,
                                               rules.get("post_type_canonical", {}))
                if canon.lower() in holiday_types and \
                   abs((post.date - h["date"]).days) <= window:
                    found = True
                    break
            row[code] = "✅" if found else "❌"
        rows.append(row)

    if not rows:
        st.write("В этом месяце обязательных праздников нет.")
        return

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(f"✅ — есть пост типа «Праздник»/«Поздравление» в пределах "
               f"±{window} дней. ❌ — не запланирован. «—» — праздник не для "
               f"этого бренда.")

    bad = [h for h in cal if h["date"] is None]
    if bad:
        with st.expander("Праздники с нераспознанной датой"):
            for h in bad:
                st.write(f"• {h['name']} — {h['date_raw']!r}")
