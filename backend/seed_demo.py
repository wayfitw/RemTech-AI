"""Заполнение БД демо-данными для просмотра админ-панели.
Запуск: .venv\\Scripts\\python.exe seed_demo.py
Очищает динамические таблицы и создаёт сотрудников, чаты, сообщения, файлы, журнал."""
import datetime as dt
import json

import auth
import db
from db import _conn

db.init_db()


def iso(days_ago: int, hour: int = 10, minute: int = 0) -> str:
    d = dt.datetime.now() - dt.timedelta(days=days_ago)
    d = d.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return d.strftime("%Y-%m-%d %H:%M:%S")


def reset():
    with _conn() as c:
        for t in ("chat_history", "uploaded_files", "activity_log", "conversations", "users"):
            c.execute(f"DELETE FROM {t}")
        c.commit()


def make_user(username, full_name, role, created_days_ago):
    u = db.create_user(username, auth.hash_password("1234"), role, full_name)
    with _conn() as c:
        c.execute("UPDATE users SET created_at=? WHERE id=?", (iso(created_days_ago, 9), u["id"]))
        c.commit()
    return u["id"]


def add_login(user_id, day, hour=9):
    with _conn() as c:
        c.execute(
            "INSERT INTO activity_log (user_id, action, detail, created_at) VALUES (?,?,?,?)",
            (user_id, "login", "Вход в систему", iso(day, hour)),
        )
        c.commit()


def add_conv(user_id, title, day, msgs, files=None):
    """msgs: list of (role, text, hour, minute). files: list of (name, kind)."""
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO conversations (user_id, title, created_at, updated_at) VALUES (?,?,?,?)",
            (user_id, title, iso(day, 10), iso(day, 12)),
        )
        cid = cur.lastrowid
        for role, text, hh, mm in msgs:
            c.execute(
                "INSERT INTO chat_history (conversation_id, user_id, role, content, created_at) "
                "VALUES (?,?,?,?,?)",
                (cid, user_id, role, json.dumps(text, ensure_ascii=False), iso(day, hh, mm)),
            )
            if role == "user":
                c.execute(
                    "INSERT INTO activity_log (user_id, action, detail, created_at) VALUES (?,?,?,?)",
                    (user_id, "message", text[:80], iso(day, hh, mm)),
                )
        for name, kind in (files or []):
            c.execute(
                "INSERT INTO uploaded_files (conversation_id, user_id, kind, file_name, file_path, "
                "direction, created_at) VALUES (?,?,?,?,?,?,?)",
                (cid, user_id, kind, name, "demo/" + name, "output", iso(day, 11)),
            )
        c.commit()
    return cid


reset()

# ── Пользователи ──────────────────────────────────────────────────────────────
director = make_user("director", "Дмитрий Гарнов", "admin", 14)
anna = make_user("anna", "Анна Смирнова", "user", 13)
igor = make_user("igor", "Игорь Волков", "user", 12)
elena = make_user("elena", "Елена Кузнецова", "user", 10)
pavel = make_user("pavel", "Павел Орлов", "user", 7)

# ── Входы (для журнала и «активны сегодня») ───────────────────────────────────
for uid in (director, anna, igor, elena, pavel):
    for day in (0, 1, 3, 6):
        add_login(uid, day, hour=8 + uid % 3)

# ── Чаты с ассистентом ────────────────────────────────────────────────────────
add_conv(anna, "КП на экскаватор XCMG XE215C", 0, [
    ("user", "Сделай КП на гусеничный экскаватор XCMG XE215C с наценкой 12%", 10, 5),
    ("assistant", "Подготовил коммерческое предложение: XCMG XE215C, базовая цена 9 850 000 ₽, "
                  "с наценкой 12% — 11 032 000 ₽, условия поставки 45 дней, гарантия 12 мес.", 10, 6),
    ("user", "Добавь строку про сервисное обслуживание", 10, 12),
    ("assistant", "Готово. Добавил раздел: плановое ТО каждые 250 м/ч, выезд сервисной бригады по Сахалину.", 10, 13),
], files=[("КП_XE215C.docx", "docx"), ("КП_XE215C.pdf", "pdf")])

add_conv(anna, "Цены на запчасти XCMG", 2, [
    ("user", "Найди цены на основные запчасти для XCMG LW300", 11, 0),
    ("assistant",
     "Подобрал цены на ходовые запчасти **XCMG LW300FN**:\n\n"
     "| Запчасть | Артикул | Оригинал | Аналог |\n"
     "|---|---|---|---|\n"
     "| Гидронасос | 803004093 | 78 000–92 000 ₽ | 41 000 ₽ |\n"
     "| Фильтр масляный | 860126442 | 1 850 ₽ | 740 ₽ |\n"
     "| Диск тормозной | 860116995 | 12 400 ₽ | 6 900 ₽ |\n\n"
     "### Сроки поставки\n"
     "- **Оригинал:** 20–30 дней\n"
     "- **Аналог:** 5–7 дней со склада\n\n"
     "> Рекомендую аналоги для расходников и оригинал — для гидравлики.", 11, 1),
], files=[])

add_conv(anna, "Письмо клиенту о задержке", 13, [
    ("user", "Напиши вежливое письмо клиенту о переносе сроков поставки на 10 дней", 9, 30),
    ("assistant", "Подготовил письмо с извинениями, объяснением причины (логистика) и новой датой.", 9, 31),
], files=[("Письмо_клиенту.docx", "docx")])

add_conv(igor, "Договор поставки спецтехники", 1, [
    ("user", "Составь договор поставки фронтального погрузчика XCMG LW500FN", 14, 0),
    ("assistant", "Сформировал договор поставки: предмет, цена, сроки, гарантия, реквизиты. "
                  "Проверь раздел 4 (порядок оплаты).", 14, 2),
    ("user", "Поменяй предоплату на 30%", 14, 20),
    ("assistant", "Изменил: предоплата 30%, остаток в течение 5 дней после поставки.", 14, 21),
], files=[("Договор_LW500FN.docx", "docx")])

add_conv(igor, "Гарантийные обязательства", 5, [
    ("user", "Какие стандартные гарантийные сроки на технику XCMG?", 13, 0),
    ("assistant", "Стандарт XCMG: 12 месяцев или 2000 м/ч (что раньше). На двигатель и гидравлику "
                  "часто отдельные условия — уточняй по модели.", 13, 1),
])

add_conv(elena, "Письмо поставщику", 3, [
    ("user", "Напиши запрос поставщику о наличии катков XCMG XS123", 10, 15),
    ("assistant", "Подготовил официальный запрос о наличии, цене и сроках поставки XS123.", 10, 16),
], files=[("Запрос_XS123.docx", "docx")])

add_conv(elena, "Сравнение фронтальных погрузчиков", 8, [
    ("user", "Сравни XCMG LW300FN и LW500FN по грузоподъёмности и цене", 11, 30),
    ("assistant", "LW300FN: 3 т, ~5,9 млн ₽. LW500FN: 5 т, ~7,8 млн ₽. Для складских задач хватит "
                  "LW300, для карьера — LW500.", 11, 31),
])

add_conv(pavel, "Тендер на дорожную технику", 0, [
    ("user", "Проверь требования тендера на поставку 3 катков для дорожного управления", 15, 0),
    ("assistant", "Ключевые требования: масса от 12 т, гарантия 24 мес, поставка до 30 дней. "
                  "XCMG XS143J подходит по всем пунктам.", 15, 2),
])

add_conv(pavel, "Спецификация катка XCMG", 11, [
    ("user", "Сделай спецификацию на грунтовый каток XCMG XS143J", 12, 0),
    ("assistant", "Сформировал спецификацию: масса 14 т, ширина вальца 2130 мм, двигатель Cummins, "
                  "вибрационная система.", 12, 1),
], files=[("Спецификация_XS143J.pdf", "pdf")])

print("Демо-данные созданы.")
print("Сотрудников:", db.count_registered_users())
print("Вход админа — логин: director, пароль: 1234")
