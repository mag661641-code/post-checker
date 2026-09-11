"""Страница «Праздники»: календарь месяца и наличие постов у брендов."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import streamlit as st

from ui_common import cached_load, get_config, page_setup, require_file
from checker import holidays_mod
from checker.normalize import canonical_post_type

page_setup("Праздники", "🎉")
st.title("Обязательные праздники")

file_bytes = require_file()
if not file_bytes:
    st.stop()

wb = cached_load(file_bytes)
cfg = get_config()
brands = cfg["brands"]
rules = cfg["rules"]

c1, c2 = st.columns(2)
year = c1.number_input("Год", min_value=2020, max_value=2035,
                       value=dt.date.today().year, step=1)
month_names = ["Все"] + ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
                         "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
month_sel = c2.selectbox("Месяц", month_names, index=dt.date.today().month)
month = None if month_sel == "Все" else month_names.index(month_sel)

cal = holidays_mod.build_holiday_calendar(wb.holidays_raw, int(year))
window = rules.get("thresholds", {}).get("holiday_window_days", 3)
holiday_types = {"праздник", "поздравление"}

rows = []
for h in cal:
    if h["date"] is None:
        continue
    if month and h["date"].month != month:
        continue
    row = {"Дата": h["date"].strftime("%d.%m.%Y"), "Праздник": h["name"],
           "Тип": h["type"]}
    targets = [h["corp_brand"]] if h["corp_brand"] else list(brands.keys())
    for code in brands.keys():
        if code not in targets:
            row[code] = "—"
            continue
        found = False
        for post in wb.posts.get(code, []):
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
    st.info("Для выбранного периода праздников с распознанной датой нет.")
else:
    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(f"✅ — есть пост типа «Праздник»/«Поздравление» в пределах "
               f"±{window} дней. ❌ — не запланирован. «—» — праздник не для "
               f"этого бренда.")

# праздники с нераспознанной датой
bad = [h for h in cal if h["date"] is None]
if bad:
    with st.expander("Праздники с нераспознанной датой"):
        for h in bad:
            st.write(f"• {h['name']} — {h['date_raw']!r}")
