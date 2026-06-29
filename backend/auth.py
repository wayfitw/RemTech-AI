"""Авторизация (Этап 2): аккаунты сотрудников — логин/пароль, роли admin/user, JWT.
Пароли хешируются через pbkdf2-hmac-sha256 (stdlib, без нативных зависимостей).
Первый зарегистрированный аккаунт становится администратором."""
import datetime as dt
import hashlib
import hmac
import os

import jwt

import db
from config import JWT_SECRET, JWT_TTL_HOURS

ALGO = "HS256"
_ITERATIONS = 200_000


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

def make_token(user: dict) -> str:
    payload = {
        "sub": str(user["id"]),
        "username": user["username"],
        "name": user.get("full_name") or user["username"],
        "role": user.get("role", "user"),
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=JWT_TTL_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGO)


def verify(token: str) -> dict | None:
    try:
        p = jwt.decode(token, JWT_SECRET, algorithms=[ALGO])
        return {
            "user_id": int(p["sub"]),
            "username": p.get("username", ""),
            "name": p.get("name", ""),
            "role": p.get("role", "user"),
        }
    except Exception:
        return None


# ── Регистрация / вход ────────────────────────────────────────────────────────

def register(username: str, password: str, full_name: str = "") -> tuple[str | None, str | None]:
    username = (username or "").strip()
    full_name = (full_name or "").strip()
    if len(username) < 3:
        return None, "Логин слишком короткий (минимум 3 символа)"
    if len(password) < 4:
        return None, "Пароль слишком короткий (минимум 4 символа)"
    if db.get_user_by_username(username):
        return None, "Такой логин уже занят"
    role = "admin" if db.count_registered_users() == 0 else "user"
    user = db.create_user(username, hash_password(password), role, full_name)
    return make_token(user), None


def login(username: str, password: str) -> tuple[str | None, str | None]:
    user = db.get_user_by_username((username or "").strip())
    if not user or not user.get("password_hash"):
        return None, "Неверный логин или пароль"
    if not user.get("active", 1):
        return None, "Аккаунт деактивирован — обратитесь к администратору"
    if not verify_password(password, user["password_hash"]):
        return None, "Неверный логин или пароль"
    return make_token(user), None
