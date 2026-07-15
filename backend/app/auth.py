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

def make_token(user, kind: str = "access") -> str:
    """#38 — access (короткий) или refresh (долгий) токен. Оба несут версию tv
    (#4) для отзыва; typ различает тип, чтобы refresh нельзя было выдать за access."""
    ttl = (dt.timedelta(minutes=settings.access_ttl_minutes) if kind == "access"
           else dt.timedelta(hours=settings.refresh_ttl_hours))
    payload = {
        "sub": str(user.id),
        "username": user.username,
        "name": user.full_name or user.username,
        "role": user.role,
        "tv": int(getattr(user, "token_version", 0) or 0),   # issue #4 — версия для отзыва
        "typ": kind,
        "exp": dt.datetime.now(dt.timezone.utc) + ttl,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGO)


def verify(token: str, typ: str | None = None) -> dict | None:
    try:
        p = jwt.decode(token, settings.jwt_secret, algorithms=[ALGO])
        if typ is not None and p.get("typ", "access") != typ:
            return None   # refresh нельзя использовать как access и наоборот
        return {"user_id": int(p["sub"]), "username": p.get("username", ""),
                "name": p.get("name", ""), "role": p.get("role", "user"),
                "tv": int(p.get("tv", 0)), "typ": p.get("typ", "access")}
    except Exception:
        return None


# ── Регистрация / вход (async) ─────────────────────────────────────────────────

async def registration_open(s) -> bool:
    return (await repo.count_registered_users(s)) == 0


MIN_PASSWORD_LEN = 8


def validate_password(password: str) -> str | None:
    """Единая парольная политика (issue #10): длина + буквы и цифры."""
    if len(password) < MIN_PASSWORD_LEN:
        return f"Пароль слишком короткий (минимум {MIN_PASSWORD_LEN} символов)"
    if not (any(c.isalpha() for c in password) and any(c.isdigit() for c in password)):
        return "Пароль должен содержать буквы и цифры"
    return None


def _validate(username: str, password: str) -> str | None:
    if len(username.strip()) < 3:
        return "Логин слишком короткий (минимум 3 символа)"
    return validate_password(password)


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
