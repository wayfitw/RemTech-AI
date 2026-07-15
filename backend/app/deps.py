"""Общие зависимости и хелперы FastAPI (issue #18 — вынесено из монолита main.py).

Здесь: авторизация (current_user/admin_user), проверка токена по БД, ролевой
доступ к агентам, лимитеры частоты, чтение загрузки с лимитом, сериализаторы.
"""
from fastapi import Depends, HTTPException, Request, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth
from app import repositories as repo
from app.config import get_settings
from app.database import get_db
from app.embeddings import get_embedder
from app.logging_config import get_logger, setup_logging
from app.ratelimit import RateLimiter

settings = get_settings()
setup_logging(settings.log_level)
log = get_logger("remtech.api")

_MAX_UPLOAD = settings.max_upload_mb * 1024 * 1024

# Issue #3 — лимиты частоты для чувствительных эндпоинтов (in-memory, на процесс).
_login_limiter = RateLimiter(max_events=10, window_seconds=300)     # вход: 10 / 5 мин на ip+логин
_register_limiter = RateLimiter(max_events=5, window_seconds=3600)  # регистрация: 5 / час на ip
_ws_limiter = RateLimiter(max_events=30, window_seconds=60)         # сообщения ws: 30 / мин на пользователя

_bearer = HTTPBearer(auto_error=False)


async def _user_from_token(token: str, db: AsyncSession) -> dict | None:
    """Issue #4 — проверка токена со сверкой active/роли/версии по БД, чтобы
    деактивация, смена роли и отзыв (logout/смена пароля) действовали немедленно,
    а не до истечения JWT."""
    claims = auth.verify(token or "", typ="access")   # #38 — refresh как access не принимаем
    if not claims:
        return None
    u = await repo.get_user(db, claims["user_id"])
    if not u or not u.active:
        return None
    if claims.get("tv", 0) != (u.token_version or 0):   # токен отозван — версия сдвинута
        return None
    return {"user_id": u.id, "username": u.username,
            "name": u.full_name or u.username, "role": u.role}


async def current_user(request: Request,
                       cred: HTTPAuthorizationCredentials = Depends(_bearer),
                       db: AsyncSession = Depends(get_db)) -> dict:
    # #4 — токен из заголовка Authorization (API-клиенты) ИЛИ из httpOnly-cookie (браузер)
    token = cred.credentials if cred else request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise HTTPException(401, "Не авторизован")
    user = await _user_from_token(token, db)
    if not user:
        raise HTTPException(401, "Неверный токен или аккаунт деактивирован")
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Доступ только для администратора")
    return user


def role_can_use_agent(role: str, agent) -> bool:
    """Единая проверка доступа роли к агенту (листинг и исполнение).
    admin — всегда; пустой allowed_roles — доступен всем; иначе роль обязана
    входить в список (deny-by-default для перечисленных ролей)."""
    allowed = (agent.allowed_roles or "").replace(" ", "")
    return role == "admin" or not allowed or role in allowed.split(",")


async def _read_upload_limited(file: UploadFile) -> bytes:
    """Читает файл потоково с ограничением размера (issue #7 — защита от OOM/DoS)."""
    chunks, size = [], 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        size += len(chunk)
        if size > _MAX_UPLOAD:
            raise HTTPException(413, f"Файл превышает лимит {settings.max_upload_mb} МБ")
        chunks.append(chunk)
    return b"".join(chunks)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


def embedder_dep():
    return get_embedder()


def conv_dict(c) -> dict:
    return {"id": c.id, "title": c.title,
            "created_at": repo.iso(c.created_at), "updated_at": repo.iso(c.updated_at)}
