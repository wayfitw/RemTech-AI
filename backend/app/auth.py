"""Cutover Стадия 2 — авторизация на async-слое.

Пароли: pbkdf2-hmac-sha256 (stdlib). JWT: HS256. Регистрация — только для
первого (админского) аккаунта; далее аккаунты заводит администратор.
"""
import datetime as dt
import hashlib
import hmac
import os

import jwt

from app import repositories as repo
from app.config import get_settings

ALGO = "HS256"
_ITERATIONS = 200_000
settings = get_settings()


# ── Пароли ────────────────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _ITERATIONS)
    return f"{salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), _ITERATIONS)
        return hmac.compare_digest(dk.hex(), hash_hex)
    except Exception:
        return False


# ── Токены ────────────────────────────────────────────────────────────────────

def make_token(user) -> str:
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "name": user.full_name or user.username,
        "role": user.role,
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=settings.jwt_ttl_hours),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGO)


def verify(token: str) -> dict | None:
    try:
        p = jwt.decode(token, settings.jwt_secret, algorithms=[ALGO])
        return {"user_id": int(p["sub"]), "username": p.get("username", ""),
                "name": p.get("name", ""), "role": p.get("role", "user")}
    except Exception:
        return None


# ── Регистрация / вход (async) ─────────────────────────────────────────────────

async def registration_open(s) -> bool:
    return (await repo.count_registered_users(s)) == 0


def _validate(username: str, password: str) -> str | None:
    if len(username.strip()) < 3:
        return "Логин слишком короткий (минимум 3 символа)"
    if len(password) < 4:
        return "Пароль слишком короткий (минимум 4 символа)"
    return None


async def register(s, username: str, password: str,
                   full_name: str = "") -> tuple[str | None, str | None]:
    username = (username or "").strip()
    if err := _validate(username, password):
        return None, err
    if await repo.get_user_by_username(s, username):
        return None, "Такой логин уже занят"
    role = "admin" if await registration_open(s) else "user"
    user = await repo.create_user(s, username, hash_password(password), role,
                                  (full_name or "").strip())
    return make_token(user), None


async def admin_create_user(s, username: str, password: str, full_name: str = "",
                            role: str = "user") -> tuple[object | None, str | None]:
    username = (username or "").strip()
    if err := _validate(username, password):
        return None, err
    if role not in ("admin", "user"):
        role = "user"
    if await repo.get_user_by_username(s, username):
        return None, "Такой логин уже занят"
    user = await repo.create_user(s, username, hash_password(password), role,
                                  (full_name or "").strip())
    return user, None


async def login(s, username: str, password: str) -> tuple[str | None, str | None]:
    user = await repo.get_user_by_username(s, (username or "").strip())
    if not user or not user.password_hash:
        return None, "Неверный логин или пароль"
    if not user.active:
        return None, "Аккаунт деактивирован — обратитесь к администратору"
    if not verify_password(password, user.password_hash):
        return None, "Неверный логин или пароль"
    return make_token(user), None
