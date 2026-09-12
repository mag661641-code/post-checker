"""Экран «Настройки»: бренды, типы/соцсети, словарь орфографии,
скрытые замечания, пороги и лимиты."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from checker import config_mod, gsheets, loader_mod
from ui import common as C


def render() -> None:
    st.title("Настройки")
    persistent, status = C.settings_status()
    (st.success if persistent else st.warning)(status)

    tabs = st.tabs(["🔗 Источник данных", "🏷 Бренды", "✅ Проверки",
                    "📚 Словари", "🙈 Скрытые замечания", "💾 Резервная копия"])
    with tabs[0]:
        _source()
    with tabs[1]:
        _brands()
    with tabs[2]:
        _checks()
    with tabs[3]:
        _dictionaries()
    with tabs[4]:
        _ignored()
    with tabs[5]:
        _backup()


def _source() -> None:
    src = config_mod.load_source()
    sa = C.get_service_account()

    st.subheader("Ссылка на Google-таблицу")

    url = st.text_input("Ссылка на таблицу «РРП. Реестр постов/отгрузок»",
                        value=src.get("url", ""), key="src_url",
                        placeholder="https://docs.google.com/spreadsheets/d/…")

    c1, c2 = st.columns([1, 1])
    if c1.button("💾 Сохранить", key="src_save", type="primary"):
        config_mod.save_source({"method": "service_account",
                                "url": url.strip(), "refresh_minutes": 0,
                                "gids": {}})
        C.clear_source_cache()
        C.persist_all()
        st.toast("Ссылка сохранена")
        st.rerun()
    if c2.button("Проверить подключение", key="src_test"):
        expected = [loader_mod.REGISTRY_SHEET] + loader_mod.BRAND_SHEETS
        with st.spinner("Проверяем…"):
            res = gsheets.test_connection(url, "service_account", sa, expected)
        if res["ok"]:
            parts = ", ".join(f"{s['title']} — {s['rows']} строк"
                              for s in res["sheets"][:6] if s.get("rows"))
            st.success(f"Подключено: «{res['title']}», листов: "
                       f"{len(res['sheets'])}. {parts}")
        else:
            st.error(res["message"])
            if res["error"] == "no_access" and res.get("sa_email"):
                st.code(res["sa_email"], language=None)

    st.caption("Свежие правки из таблицы подтягиваются кнопкой «🔄 Обновить "
               "данные» в панели слева.")


def _clear_caches() -> None:
    # сбросить кеши и, если подключена таблица настроек, сохранить в неё
    C.persist_all()


import re
from checker import normalize as N

_PHONE_RE = re.compile(r"^\+7 \(\d{3}\) \d{3}-\d{2}-\d{2}$")


def _norm_site(site: str) -> str:
    s = (site or "").strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    return s.rstrip("/")


def _norm_hashtag(tag: str) -> str:
    t = (tag or "").strip()
    if not t:
        return ""
    t = t.lstrip("#")
    t = re.sub(r"\s+", "_", t)
    return "#" + t


def _tg_url(name: str) -> str:
    return f"https://t.me/{name}" if name else ""


def _vk_url(gid: str) -> str:
    if gid and str(gid).lstrip("-").isdigit():
        return f"https://vk.com/club{str(gid).lstrip('-')}"
    return ""


def _ok_url(gid: str) -> str:
    return f"https://ok.ru/group/{gid}" if gid else ""


def _wa_url(cid: str) -> str:
    return f"https://whatsapp.com/channel/{cid}" if cid else ""


@st.dialog("Добавить бренд")
def _add_brand_dialog(brands: dict) -> None:
    code = st.text_input("Короткий код (как в колонке «Бренд» реестра)",
                         placeholder="СМУ")
    name = st.text_input("Название", placeholder="Стальметурал")
    if st.button("Создать", type="primary"):
        code = code.strip()
        if not code:
            st.error("Укажите короткий код.")
        elif code in brands:
            st.error("Такой код уже есть.")
        else:
            brands[code] = {"name": name.strip(), "site": "", "email": "",
                            "phone": "", "required_hashtags_shipment": [],
                            "telegram": {"clients": "", "staff": ""},
                            "vk_group_id": "", "ok_group_id": "",
                            "max_channel_id": "", "whatsapp_channel": "",
                            "enabled": True}
            config_mod.save_brands(brands)
            _clear_caches()
            st.session_state["brand_sel"] = code
            st.rerun()


@st.dialog("Удалить бренд")
def _delete_brand_dialog(brands: dict, code: str) -> None:
    st.write(f"Удалить бренд «{code}»? Его посты перестанут проверяться.")
    if st.button("Удалить", type="primary"):
        brands.pop(code, None)
        config_mod.save_brands(brands)
        _clear_caches()
        st.session_state.pop("brand_sel", None)
        st.rerun()


def _extract_channel(kind: str, link: str) -> tuple[str, str]:
    """Вернуть (id, сообщение) из вставленной ссылки."""
    link = (link or "").strip()
    if not link:
        return "", ""
    if kind == "tg":
        v = N.tg_channel_from_link(link) or ""
        return v, ("Распознан канал: " + v if v else
                   "Не удалось распознать. Вставьте ссылку вида t.me/название.")
    if kind == "vk":
        v = N.vk_group_id_from_link(link) or ""
        if not v:
            m = re.search(r"club(\d+)|public(\d+)", link)
            if m:
                v = "-" + (m.group(1) or m.group(2))
        return v, ("Распознано: группа " + v if v else
                   "Из такой ссылки id не узнать — вставьте ссылку на любой пост "
                   "группы.")
    if kind == "ok":
        v = N.ok_group_id_from_link(link) or ""
        return v, ("Распознано: группа " + v if v else
                   "Не удалось распознать. Вставьте ссылку на пост группы.")
    if kind == "max":
        v = N.max_channel_id_from_link(link) or ""
        return v, ("Распознано: канал " + v if v else
                   "Не удалось распознать. Вставьте ссылку на пост канала.")
    if kind == "wa":
        v = N.whatsapp_channel_from_link(link) or ""
        return v, ("Распознан канал: " + v if v else
                   "Не удалось распознать. Вставьте ссылку вида "
                   "whatsapp.com/channel/…")
    return "", ""


def _brands() -> None:
    brands = config_mod.load_brands()
    codes = list(brands.keys())
    if not codes:
        st.info("Брендов пока нет.")
        if st.button("➕ Добавить бренд"):
            _add_brand_dialog(brands)
        return

    top = st.columns([5, 1])
    with top[0]:
        def _fmt(c):
            return c if brands[c].get("enabled", True) else f"{c} (выкл.)"
        sel = st.session_state.get("brand_sel")
        if sel not in codes:
            sel = codes[0]
        code = st.segmented_control("Бренд", codes, default=sel,
                                    format_func=_fmt, key="brand_seg")
        code = code or sel
        st.session_state["brand_sel"] = code
    with top[1]:
        st.write("")
        if st.button("➕ Добавить", key="add_brand"):
            _add_brand_dialog(brands)

    b = brands[code]

    # --- Основное ---
    with st.container(border=True):
        st.markdown("**Основное**")
        st.text_input("Короткий код", value=code, disabled=True,
                      key=f"code_{code}", help="Используется в таблице, не меняется")
        name = st.text_input("Название бренда", value=b.get("name", ""),
                             placeholder="Стальметурал", key=f"name_{code}")
        enabled = st.toggle("Проверять этот бренд",
                            value=b.get("enabled", True), key=f"en_{code}")

    # --- Контакты ---
    with st.container(border=True):
        st.markdown("**Контакты в постах**")
        cc = st.columns(3)
        site = cc[0].text_input("Сайт", value=b.get("site", ""),
                                placeholder="stalmetural.ru", key=f"site_{code}")
        email = cc[1].text_input("E-mail", value=b.get("email", ""),
                                 placeholder="info@stalmetural.ru",
                                 key=f"mail_{code}")
        phone = cc[2].text_input("Телефон", value=b.get("phone", ""),
                                 placeholder="+7 (499) 130-36-69",
                                 key=f"phone_{code}")
        if phone and not _PHONE_RE.match(phone.strip()):
            st.warning("Телефон должен быть в формате +7 (XXX) XXX-XX-XX")
        elif site and phone:
            st.caption("✅ Всё заполнено верно")
        if not email:
            st.caption("E-mail не будет проверяться в постах этого бренда.")

    # --- Хэштеги ---
    with st.container(border=True):
        st.markdown("**Хэштеги**")
        cur_tags = b.get("required_hashtags_shipment", [])
        tags = st.multiselect(
            "Обязательные хэштеги в постах-отгрузках", options=cur_tags,
            default=cur_tags, accept_new_options=True, key=f"tags_{code}",
            placeholder="Введите хэштег и нажмите Enter")
        tags = [_norm_hashtag(t) for t in tags if t.strip()]
        first_opts = ["Не важно"] + tags
        cur_first = b.get("first_hashtag_must_be") or "Не важно"
        if cur_first not in first_opts:
            first_opts.append(cur_first)
        first = st.selectbox("Хэштег, который должен стоять первым", first_opts,
                             index=first_opts.index(cur_first),
                             key=f"first_{code}")
        if tags:
            st.caption("В посте должно быть: " + " ".join(tags))

    # --- Правила проверки по типам (переопределение для бренда) ---
    all_rules = config_mod.load_rules()
    ptr = all_rules.get("post_type_rules", {})
    type_names = list(all_rules.get("post_type_canonical", {}).keys())
    brand_tr = b.get("type_rules", {}) or {}
    _kmap = {"Телефон": "phone", "Сайт": "site", "E-mail": "email",
             "Хэштеги": "hashtags"}
    with st.container(border=True):
        st.markdown("**Правила проверки по типам постов**")
        st.caption("По умолчанию берутся общие настройки типов. Здесь можно "
                   "переопределить для этого бренда.")
        rows = []
        for t in type_names:
            base = ptr.get(t, {})
            ov = brand_tr.get(t, {})

            def _val(k, base=base, ov=ov):
                return bool(ov.get(k, base.get(k, False)))
            rows.append({"Тип": t, "Телефон": _val("phone"), "Сайт": _val("site"),
                         "E-mail": _val("email"), "Хэштеги": _val("hashtags")})
        type_rules_edit = st.data_editor(
            pd.DataFrame(rows), hide_index=True, use_container_width=True,
            key=f"tr_{code}",
            column_config={
                "Тип": st.column_config.TextColumn(disabled=True),
                "Телефон": st.column_config.CheckboxColumn(),
                "Сайт": st.column_config.CheckboxColumn(),
                "E-mail": st.column_config.CheckboxColumn(),
                "Хэштеги": st.column_config.CheckboxColumn()})

    # --- Сноска для спецпредложений ---
    with st.container(border=True):
        st.markdown("**Сноска для спецпредложений**")
        footnote_val = st.text_area(
            "Текст обязательной сноски про цену и оферту",
            value=b.get("offer_footnote", ""), key=f"fn_{code}", height=90,
            placeholder="Цена актуальна на дату публикации и не является "
                        "публичной офертой…")

    # --- Каналы ---
    with st.container(border=True):
        st.markdown("**Каналы и группы в соцсетях**")
        st.caption("Вставьте ссылку на группу или любой пост — id определится сам.")
        tg = b.get("telegram", {}) if isinstance(b.get("telegram"), dict) else {}

        tg_clients = st.text_input(
            "Telegram для клиентов", value=_tg_url(tg.get("clients", "")),
            placeholder="https://t.me/stalmetural", key=f"tgc_{code}")
        cid, msg = _extract_channel("tg", tg_clients)
        if tg_clients:
            st.caption(("✅ " if cid else "⚠️ ") + msg)

        tg_staff = st.text_input(
            "Telegram для сотрудников", value=_tg_url(tg.get("staff", "")),
            placeholder="https://t.me/SMUdaily", key=f"tgs_{code}")
        sid, msg = _extract_channel("tg", tg_staff)
        if tg_staff:
            st.caption(("✅ " if sid else "⚠️ ") + msg)

        vk_link = st.text_input(
            "ВКонтакте (ссылка на пост группы)", value=_vk_url(b.get("vk_group_id", "")),
            placeholder="https://vk.com/wall-217668235_819", key=f"vk_{code}")
        vk_id, msg = _extract_channel("vk", vk_link)
        if vk_link:
            st.caption(("✅ " if vk_id else "⚠️ ") + msg)

        ok_link = st.text_input(
            "Одноклассники (ссылка на пост группы)",
            value=_ok_url(b.get("ok_group_id", "")),
            placeholder="https://ok.ru/group/70000004574376/topic/…",
            key=f"ok_{code}")
        ok_id, msg = _extract_channel("ok", ok_link)
        if ok_link:
            st.caption(("✅ " if ok_id else "⚠️ ") + msg)

        max_link = st.text_input(
            "Max (ссылка на пост канала)", value=str(b.get("max_channel_id", "")),
            placeholder="https://max.ru/c/-70916890460398/…", key=f"max_{code}")
        max_id, msg = _extract_channel("max", max_link)
        if max_link and not str(max_link).lstrip("-").isdigit():
            st.caption(("✅ " if max_id else "⚠️ ") + msg)
        else:
            max_id = str(max_link).strip()

        wa_link = st.text_input(
            "WhatsApp-канал (ссылка на канал или публикацию)",
            value=_wa_url(b.get("whatsapp_channel", "")),
            placeholder="https://whatsapp.com/channel/0029Va…", key=f"wa_{code}")
        wa_id, msg = _extract_channel("wa", wa_link)
        if wa_link:
            st.caption(("✅ " if wa_id else "⚠️ ") + msg)

    # --- предпросмотр контактного блока ---
    with st.expander("Как выглядит контактный блок"):
        block = []
        if site:
            block.append("🌐 " + _norm_site(site))
        if email:
            block.append("📩 " + email.strip())
        if phone:
            block.append("📞 " + phone.strip())
        st.text("\n".join(block) or "(контакты не заполнены)")

    # --- кнопки ---
    st.write("")
    bcols = st.columns([1.4, 1.4, 3, 1.6])
    if bcols[0].button("💾 Сохранить бренд", type="primary", key=f"save_{code}"):
        type_rules_override = {}
        for _i, r in type_rules_edit.iterrows():
            t = r["Тип"]
            base = ptr.get(t, {})
            diff = {code_key: bool(r[label]) for label, code_key in _kmap.items()
                    if bool(r[label]) != bool(base.get(code_key, False))}
            if diff:
                type_rules_override[t] = diff
        b.update({
            "offer_footnote": footnote_val.strip(),
            "type_rules": type_rules_override,
            "name": name.strip(),
            "site": _norm_site(site),
            "email": email.strip(),
            "phone": phone.strip(),
            "enabled": enabled,
            "required_hashtags_shipment": tags,
            "first_hashtag_must_be": None if first == "Не важно" else first,
            "telegram": {"clients": cid, "staff": sid},
            "vk_group_id": vk_id, "ok_group_id": ok_id,
            "max_channel_id": max_id, "whatsapp_channel": wa_id,
        })
        brands[code] = b
        config_mod.save_brands(brands)
        _clear_caches()
        st.toast("Настройки сохранены")
        st.rerun()
    if bcols[1].button("Отменить изменения", key=f"cancel_{code}"):
        st.rerun()
    if bcols[3].button("🗑 Удалить бренд", key=f"del_{code}"):
        _delete_brand_dialog(brands, code)


# ===========================================================================
# ВКЛАДКА «ПРОВЕРКИ»
# ===========================================================================
_LVL_LABEL = {"error": "🔴 Ошибка", "warning": "🟡 Предупреждение",
              "advice": "🔵 Совет"}
_LVL_FROM_LABEL = {v: k for k, v in _LVL_LABEL.items()}

# toggle_key -> (раздел, название, пояснение, [коды], уровень по умолчанию)
CHECK_META = [
    ("registry_empty_fields", "Реестр", "Пустые обязательные поля",
     "бренд, тип, статус, ссылка, исполнитель", ["reg_empty", "reg_no_executor"], "warning"),
    ("registry_bad_date", "Реестр", "Нераспознанная дата", "", ["reg_bad_date"], "error"),
    ("registry_pub_before_write", "Реестр", "Публикация раньше написания", "",
     ["reg_pub_before_write"], "warning"),
    ("registry_posted_future", "Реестр", "«Выложено», а дата в будущем", "",
     ["reg_posted_future"], "warning"),
    ("registry_ready_past", "Реестр", "«Готово», а дата прошла",
     "возможно, забыли выложить", ["reg_ready_past"], "warning"),
    ("registry_posted_private_link", "Реестр", "«Выложено» со ссылкой в чат",
     "t.me/c/…", ["reg_private_link"], "error"),
    ("registry_duplicate_links", "Реестр", "Дубли ссылок", "внутри и между строк",
     ["reg_dup_across", "reg_dup_in_cell"], "error"),
    ("registry_wrong_brand_link", "Реестр", "Ссылка чужого бренда", "",
     ["reg_wrong_brand_link"], "error"),
    ("registry_missing_platforms", "Реестр", "Неполный набор площадок", "",
     ["reg_missing_platforms"], "warning"),
    ("registry_unknown_domain", "Реестр", "Неизвестный домен", "", ["reg_unknown_domain"], "warning"),
    ("registry_post_type_spelling", "Реестр", "Написание типа поста",
     "напр., «Информативый»", ["reg_type_spelling", "text_type_spelling"], "warning"),
    ("text_contacts_present", "Контакты", "Контактный блок бренда",
     "сайт, телефон, e-mail, по типам",
     ["text_no_site", "text_no_phone", "text_no_email", "text_phone_dash",
      "text_site_anchor_no_link", "text_type_unknown"], "error"),
    ("text_offer_footnote", "Контакты", "Сноска в спецпредложении",
     "про цену и оферту", ["text_offer_footnote", "text_footnote_star"], "warning"),
    ("text_short_dash", "Типографика", "Короткое тире вместо длинного",
     "«–» → «—»", ["text_short_dash"], "warning"),
    ("text_shipment_labels", "Фото", "ЛОГО/БЕЗ ЛОГО у отгрузок",
     "нужны обе строки", ["text_shipment_labels"], "warning"),
    ("text_other_brand_contacts", "Контакты", "Контакты чужого бренда", "",
     ["text_other_contacts"], "error"),
    ("text_other_brand_name", "Контакты", "Название чужого бренда", "",
     ["text_other_name"], "error"),
    ("text_required_hashtags", "Хэштеги", "Обязательные хэштеги", "",
     ["text_missing_hashtags"], "warning"),
    ("text_mpi_first_hashtag", "Хэштеги", "Первый хэштег МПИ", "", ["text_mpi_first"], "warning"),
    ("text_repeated_hashtag", "Хэштеги", "Повтор хэштега", "", ["text_dup_hashtag"], "advice"),
    ("text_weird_hashtag", "Хэштеги", "Странный хэштег",
     "цифра в конце и т.п.", ["text_weird_hashtag"], "warning"),
    ("text_placeholders", "Шаблоны", "Заглушки в скобках", "напр., [Город]",
     ["text_placeholder"], "error"),
    ("text_prompt_leftovers", "Шаблоны", "Куски промта в тексте", "",
     ["text_prompt"], "error"),
    ("text_markdown_stars", "Шаблоны", "Звёздочки разметки *…*", "", ["text_stars"], "warning"),
    ("text_long_dashes", "Типографика", "Длинные тире «—»", "больше порога",
     ["text_dashes"], "advice"),
    ("text_colon_in_list", "Типографика", "Двоеточие в пунктах списка",
     "МПЭ, АПС, МПИ", ["text_list_colon"], "warning"),
    ("text_whitespace", "Типографика", "Лишние пробелы и пустые строки", "",
     ["text_double_space", "text_trailing_space", "text_blank_lines"], "advice"),
    ("text_doubled_letter", "Типографика", "Удвоенная буква", "напр., «Рработает»",
     ["text_doubled_letter"], "warning"),
    ("text_doubled_word", "Типографика", "Два одинаковых слова подряд", "",
     ["text_doubled_word"], "warning"),
    ("text_mixed_quotes", "Типографика", "Смешаны кавычки", "«ёлочки» и \"лапки\"",
     ["text_mixed_quotes"], "advice"),
    ("text_hard_wraps", "Типографика", "Жёсткие переносы строк", "",
     ["text_hard_wrap"], "warning"),
    ("text_telegram_length", "Типографика", "Длина текста для Telegram",
     "подпись к фото", ["text_tg_caption"], "warning"),
    ("text_link_domain", "Контакты", "Ссылка на чужой сайт", "", ["text_foreign_domain"], "warning"),
    ("text_info_needs_link", "Шаблоны", "Ссылка в конце инфопоста", "",
     ["text_info_no_link"], "warning"),
    ("text_photo_empty", "Фото", "Нет фото у поста", "", ["text_no_photo"], "warning"),
    ("text_photo_filename", "Фото", "Вместо ссылки имя файла", "", ["text_photo_name"], "warning"),
]


def _checks() -> None:
    rules = config_mod.load_rules()
    toggles = rules.get("toggles", {})
    levels = rules.get("check_levels", {})

    rows = []
    for key, section, name, explain, codes, default_lvl in CHECK_META:
        cur_lvl = levels.get(codes[0], default_lvl)
        rows.append({
            "Раздел": section, "Проверка": name, "Пояснение": explain,
            "Включена": bool(toggles.get(key, True)),
            "Уровень": _LVL_LABEL.get(cur_lvl, _LVL_LABEL[default_lvl]),
        })
    df = pd.DataFrame(rows)
    edited = st.data_editor(
        df, use_container_width=True, hide_index=True, height=460,
        key="checks_editor",
        column_config={
            "Раздел": st.column_config.TextColumn(disabled=True, width="small"),
            "Проверка": st.column_config.TextColumn(disabled=True, width="medium"),
            "Пояснение": st.column_config.TextColumn(disabled=True, width="medium"),
            "Включена": st.column_config.CheckboxColumn(),
            "Уровень": st.column_config.SelectboxColumn(
                options=list(_LVL_LABEL.values())),
        })

    st.markdown("**Числовые параметры**")
    th = rules.get("thresholds", {})
    online = rules.get("online", {})
    cc = st.columns(3)
    dash = cc[0].number_input("Допустимо длинных тире на пост", 0, 50,
                              int(th.get("long_dash_max", 3)), key="th_dash")
    cap = cc[1].number_input("Лимит подписи к фото (Telegram)", 100, 4096,
                             int(th.get("telegram_caption_limit", 1024)), key="th_cap")
    msg = cc[2].number_input("Лимит сообщения (Telegram)", 100, 8192,
                             int(th.get("telegram_message_limit", 4096)), key="th_msg")
    cc2 = st.columns(3)
    win = cc2[0].number_input("Окно поиска поста к празднику, ± дней", 0, 30,
                              int(th.get("holiday_window_days", 3)), key="th_win")
    sim = cc2[1].number_input("Порог схожести текста, %", 0, 100,
                              int(th.get("online_similarity_threshold", 85)), key="th_sim")
    pause = cc2[2].number_input("Пауза между запросами, сек", 0.0, 10.0,
                                float(online.get("pause_seconds", 1.0)), step=0.5,
                                key="th_pause")

    c1, c2 = st.columns([1, 1])
    if c1.button("💾 Сохранить", key="checks_save", type="primary"):
        for i, (key, *_rest, codes, _dl) in enumerate(CHECK_META):
            rules.setdefault("toggles", {})[key] = bool(edited.iloc[i]["Включена"])
            lvl = _LVL_FROM_LABEL.get(edited.iloc[i]["Уровень"], _dl)
            for code in codes:
                rules.setdefault("check_levels", {})[code] = lvl
        rules.setdefault("thresholds", {}).update({
            "long_dash_max": int(dash), "telegram_caption_limit": int(cap),
            "telegram_message_limit": int(msg), "holiday_window_days": int(win),
            "online_similarity_threshold": int(sim)})
        rules.setdefault("online", {})["pause_seconds"] = float(pause)
        config_mod.save_rules(rules)
        _clear_caches()
        st.toast("Настройки сохранены")
        st.rerun()
    if c2.button("Отменить изменения", key="checks_cancel"):
        st.rerun()


# ===========================================================================
# ВКЛАДКА «СЛОВАРИ»
# ===========================================================================
def _dictionaries() -> None:
    rules = config_mod.load_rules()

    types = rules.get("post_type_canonical", {})
    with st.expander(f"Типы постов ({len(types)})"):
        _dict_types(rules)

    socials = rules.get("social_canonical", {})
    with st.expander(f"Названия соцсетей ({len(socials)})"):
        _dict_socials(rules)

    phrases = rules.get("prompt_leftover_phrases", [])
    with st.expander(f"Стоп-фразы ({len(phrases)})"):
        _dict_stopphrases(rules)

    words = config_mod.load_whitelist()
    with st.expander(f"Словарь орфографии ({len(words)})"):
        _dict_spelling()


def _dict_types(rules: dict) -> None:
    types = rules.get("post_type_canonical", {})
    ptr = rules.get("post_type_rules", {})
    new_vals = {}
    for canon, variants in types.items():
        with st.container(border=True):
            st.markdown(f"**{canon}**")
            v = st.multiselect("Как ещё пишут в таблице", options=variants,
                               default=variants, accept_new_options=True,
                               key=f"tv_{canon}",
                               placeholder="добавьте вариант написания")
            cur = ptr.get(canon, {})
            st.caption("Что проверять в посте этого типа:")
            cc = st.columns(4)
            phone = cc[0].checkbox("Телефон", value=bool(cur.get("phone", False)),
                                   key=f"tp_{canon}")
            site = cc[1].checkbox("Сайт", value=bool(cur.get("site", False)),
                                  key=f"ts_{canon}")
            email = cc[2].checkbox("E-mail", value=bool(cur.get("email", False)),
                                   key=f"te_{canon}")
            hashtags = cc[3].checkbox("Хэштеги", value=bool(cur.get("hashtags", False)),
                                      key=f"tht_{canon}")
            new_vals[canon] = (v, phone, site, email, hashtags)

    st.caption("Галочки — общие значения по умолчанию для всех брендов. "
               "Отличия конкретного бренда задаются в «Бренды» → «Правила "
               "проверки по типам».")
    if st.button("💾 Сохранить типы", key="types_save", type="primary"):
        rules["post_type_canonical"] = {c: v for c, (v, *_r) in new_vals.items()}
        rules["post_type_rules"] = {
            c: {"phone": p, "site": s, "email": e, "hashtags": h}
            for c, (_v, p, s, e, h) in new_vals.items()}
        config_mod.save_rules(rules)
        _clear_caches()
        st.toast("Настройки сохранены")
        st.rerun()


def _dict_socials(rules: dict) -> None:
    socials = rules.get("social_canonical", {})
    new = {}
    for canon, variants in socials.items():
        v = st.multiselect(canon, options=variants, default=variants,
                           accept_new_options=True, key=f"soc_{canon}",
                           placeholder="как ещё пишут в таблице")
        new[canon] = v
    if st.button("💾 Сохранить соцсети", key="soc_save", type="primary"):
        rules["social_canonical"] = new
        config_mod.save_rules(rules)
        _clear_caches()
        st.toast("Настройки сохранены")
        st.rerun()


def _dict_stopphrases(rules: dict) -> None:
    st.caption("Если в тексте поста встретится такая фраза — это ошибка: "
               "в пост попал кусок промта.")
    phrases = rules.get("prompt_leftover_phrases", [])
    v = st.multiselect("Стоп-фразы", options=phrases, default=phrases,
                       accept_new_options=True, key="stopphrases",
                       placeholder="добавьте фразу")
    if st.button("💾 Сохранить стоп-фразы", key="sp_save", type="primary"):
        rules["prompt_leftover_phrases"] = v
        config_mod.save_rules(rules)
        _clear_caches()
        st.toast("Настройки сохранены")
        st.rerun()


def _dict_spelling() -> None:
    words = sorted(config_mod.load_whitelist())
    q = st.text_input("Поиск по словарю", key="wl_search",
                      placeholder="начните вводить слово")
    shown = [w for w in words if q.lower() in w.lower()] if q else words
    v = st.multiselect("Слова словаря", options=shown, default=shown,
                       accept_new_options=True, key="wl_tags",
                       placeholder="добавьте слово")
    bulk = st.text_area("Добавить сразу много слов (через запятую или с новой "
                        "строки)", key="wl_bulk", height=100)
    if st.button("💾 Сохранить словарь", key="wl_save", type="primary"):
        result = set(words) if q else set()
        result.update(v)
        for chunk in re.split(r"[,\n]", bulk):
            if chunk.strip():
                result.add(chunk.strip())
        added = len(result) - len(words)
        config_mod.save_whitelist(result)
        _clear_caches()
        st.toast(f"Сохранено. Добавлено новых слов: {max(0, added)}")
        st.rerun()


# ===========================================================================
# ВКЛАДКА «СКРЫТЫЕ ЗАМЕЧАНИЯ»
# ===========================================================================
def _ignored() -> None:
    data = config_mod.load_ignored()
    if not data:
        st.info("Скрытых замечаний нет. Кнопка «Не ошибка» в карточке поста "
                "добавляет замечания сюда.")
        return
    st.caption("Замечания, скрытые кнопкой «Не ошибка». Отметьте и верните нужные.")
    names = {}
    for key, section, name, explain, codes, default_lvl in CHECK_META:
        for code in codes:
            names[code] = name
    rows = []
    keys = list(data.keys())
    for key in keys:
        info = data[key]
        rows.append({
            "Вернуть": False,
            "Скрыто": info.get("added", ""),
            "Лист": info.get("sheet", ""),
            "Строка": info.get("row", ""),
            "Проверка": names.get(info.get("code", ""), info.get("code", "")),
        })
    edited = st.data_editor(
        pd.DataFrame(rows), use_container_width=True, hide_index=True,
        key="ignored_editor",
        column_config={"Вернуть": st.column_config.CheckboxColumn(),
                       "Лист": st.column_config.TextColumn(disabled=True),
                       "Строка": st.column_config.TextColumn(disabled=True),
                       "Проверка": st.column_config.TextColumn(disabled=True),
                       "Скрыто": st.column_config.TextColumn(disabled=True)})
    if st.button("Вернуть выбранные", key="unig_save", type="primary"):
        for i, key in enumerate(keys):
            if bool(edited.iloc[i]["Вернуть"]):
                config_mod.remove_ignored(key)
        _clear_caches()
        st.toast("Готово")
        st.rerun()


# ===========================================================================
# ВКЛАДКА «РЕЗЕРВНАЯ КОПИЯ И ДОСТУП»
# ===========================================================================
def _current_bundle() -> dict:
    return {
        "brands": config_mod.load_brands(),
        "rules": config_mod.load_rules(),
        "whitelist": sorted(config_mod.load_whitelist()),
        "ignored": config_mod.load_ignored(),
        "manual": config_mod.load_manual(),
        "source": config_mod.load_source(),
    }


@st.dialog("Загрузить настройки из файла")
def _restore_dialog(bundle: dict) -> None:
    st.write("Будут заменены: бренды, проверки, словари, скрытые замечания, "
             "ссылка на таблицу.")
    st.caption(f"Брендов: {len(bundle.get('brands', {}))}, "
               f"слов в словаре: {len(bundle.get('whitelist', []))}, "
               f"скрытых замечаний: {len(bundle.get('ignored', {}))}.")
    if st.button("Заменить настройки", type="primary"):
        _apply_bundle(bundle)
        st.rerun()


@st.dialog("Сбросить все настройки")
def _reset_dialog() -> None:
    st.write("Вы уверены? Бренды, словари и скрытые замечания вернутся "
             "к исходным.")
    if st.button("Сбросить всё", type="primary"):
        config_mod.save_brands(config_mod.get_default("brands"))
        config_mod.save_rules(config_mod.get_default("rules"))
        config_mod.save_whitelist(config_mod.get_default("whitelist"))
        config_mod.save_ignored({})
        _clear_caches()
        st.rerun()


def _apply_bundle(bundle: dict) -> None:
    if "brands" in bundle:
        config_mod.save_brands(bundle["brands"])
    if "rules" in bundle:
        config_mod.save_rules(bundle["rules"])
    if "whitelist" in bundle:
        config_mod.save_whitelist(bundle["whitelist"])
    if "ignored" in bundle:
        config_mod.save_ignored(bundle["ignored"])
    if "manual" in bundle:
        config_mod.save_manual(bundle["manual"])
    if "source" in bundle:
        config_mod.save_source(bundle["source"])
    _clear_caches()


def _backup() -> None:
    import datetime as dt
    st.subheader("Резервная копия")
    stamp = dt.date.today().isoformat()
    st.download_button(
        "📥 Скачать все настройки",
        data=json.dumps(_current_bundle(), ensure_ascii=False, indent=2),
        file_name=f"nastroyki_proverki_{stamp}.json",
        mime="application/json", key="backup_dl")

    up = st.file_uploader("📤 Загрузить настройки из файла", type=["json"],
                          key="backup_up")
    if up is not None:
        try:
            bundle = json.loads(up.getvalue().decode("utf-8"))
            if st.button("Просмотреть и заменить", key="restore_btn"):
                _restore_dialog(bundle)
        except Exception as e:  # noqa: BLE001
            st.error(f"Не удалось прочитать файл: {e}")

    st.divider()
    if st.button("Сбросить всё к стандартным", key="reset_all"):
        _reset_dialog()

    st.divider()
    st.subheader("Доступ")
    try:
        has_pw = bool(st.secrets.get("auth", {}).get("password"))  # type: ignore
    except Exception:  # noqa: BLE001
        has_pw = False
    if has_pw:
        st.write("🔒 Вход по паролю включён.")
    else:
        st.write("⚠️ Сервис открыт всем, у кого есть ссылка.")
    st.caption("Пароль задаётся только в секретах Streamlit (Manage app → "
               "Settings → Secrets), в интерфейсе не меняется.")
