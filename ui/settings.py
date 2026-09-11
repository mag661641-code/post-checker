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

    tabs = st.tabs(["🔗 Источник данных", "Бренды", "Типы постов и соцсети",
                    "Словарь орфографии", "Скрытые замечания", "Пороги и лимиты"])
    with tabs[0]:
        _source()
    with tabs[1]:
        _brands()
    with tabs[2]:
        _types_socials()
    with tabs[3]:
        _whitelist()
    with tabs[4]:
        _ignored()
    with tabs[5]:
        _thresholds()


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
    C.cached_base_checks.clear()
    C.cached_spell.clear()


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
                            "max_channel_id": "", "enabled": True}
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
        b.update({
            "name": name.strip(),
            "site": _norm_site(site),
            "email": email.strip(),
            "phone": phone.strip(),
            "enabled": enabled,
            "required_hashtags_shipment": tags,
            "first_hashtag_must_be": None if first == "Не важно" else first,
            "telegram": {"clients": cid, "staff": sid},
            "vk_group_id": vk_id, "ok_group_id": ok_id,
            "max_channel_id": max_id,
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


def _types_socials() -> None:
    rules = config_mod.load_rules()
    st.write("Словари приведения написаний к эталону (тип поста, соцсеть).")
    types_json = st.text_area(
        "Типы постов (эталон → варианты написания)",
        json.dumps(rules.get("post_type_canonical", {}), ensure_ascii=False,
                   indent=2), height=200, key="s_types")
    soc_json = st.text_area(
        "Соцсети (эталон → варианты написания)",
        json.dumps(rules.get("social_canonical", {}), ensure_ascii=False,
                   indent=2), height=200, key="s_soc")
    c1, c2 = st.columns(2)
    if c1.button("Сохранить", key="s_types_save", type="primary"):
        try:
            rules["post_type_canonical"] = json.loads(types_json)
            rules["social_canonical"] = json.loads(soc_json)
            config_mod.save_rules(rules)
            _clear_caches()
            st.success("Сохранено.")
        except json.JSONDecodeError as e:
            st.error(f"Ошибка в JSON: {e}")
    if c2.button("Вернуть стандартные", key="s_types_reset"):
        config_mod.save_rules(config_mod.get_default("rules"))
        _clear_caches()
        st.success("Возвращены стандартные значения.")


def _whitelist() -> None:
    words = sorted(config_mod.load_whitelist())
    st.write("Слова, которые не считаются ошибками орфографии.")
    txt = st.text_area("Одно слово на строку", "\n".join(words), height=320,
                       key="s_wl")
    c1, c2 = st.columns(2)
    if c1.button("Сохранить", key="s_wl_save", type="primary"):
        config_mod.save_whitelist(txt.splitlines())
        _clear_caches()
        st.success("Сохранено.")
    if c2.button("Вернуть стандартные", key="s_wl_reset"):
        config_mod.save_whitelist(config_mod.get_default("whitelist"))
        _clear_caches()
        st.success("Возвращены стандартные значения.")


def _ignored() -> None:
    data = config_mod.load_ignored()
    if not data:
        st.info("Скрытых замечаний нет. Кнопка «Не ошибка» в карточке поста "
                "добавляет замечания сюда.")
        return
    st.write("Замечания, помеченные как «не ошибка». Их можно вернуть.")
    for key, info in list(data.items()):
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"Лист «{info.get('sheet')}», строка {info.get('row')} — "
                    f"проверка `{info.get('code')}`")
        if c2.button("Вернуть", key=f"unig_{key}"):
            config_mod.remove_ignored(key)
            _clear_caches()
            st.rerun()


def _thresholds() -> None:
    rules = config_mod.load_rules()
    th = rules.get("thresholds", {})
    rows = [{"Параметр": k, "Значение": v} for k, v in th.items()]
    edited = st.data_editor(pd.DataFrame(rows), use_container_width=True,
                            hide_index=True, key="s_th")
    st.caption("Ожидаемые площадки, известные домены и прочее — в полном JSON "
               "на странице ниже.")
    rules_json = st.text_area("rules.json (всё остальное)",
                              json.dumps(rules, ensure_ascii=False, indent=2),
                              height=240, key="s_rules_json")
    c1, c2 = st.columns(2)
    if c1.button("Сохранить", key="s_th_save", type="primary"):
        try:
            data = json.loads(rules_json)
            new_th = {}
            for _, r in edited.iterrows():
                v = r["Значение"]
                try:
                    v = int(v) if float(v) == int(float(v)) else float(v)
                except (ValueError, TypeError):
                    pass
                new_th[r["Параметр"]] = v
            data["thresholds"] = new_th
            config_mod.save_rules(data)
            _clear_caches()
            st.success("Сохранено.")
        except json.JSONDecodeError as e:
            st.error(f"Ошибка в JSON: {e}")
    if c2.button("Вернуть стандартные", key="s_th_reset"):
        config_mod.save_rules(config_mod.get_default("rules"))
        _clear_caches()
        st.success("Возвращены стандартные значения.")
