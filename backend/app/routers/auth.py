"""Роутер авторизации: health, статус регистрации, регистрация, вход, профиль."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth, cookies
from app import repositories as repo
from app.database import get_db
from app.deps import (
    _client_ip,
    _login_limiter,
    _register_limiter,
    current_user,
    log,
)
from app.schemas import LoginReq, RegisterReq
from app.tickets import tickets

router = APIRouter()


@router.get("/api/health")
async def health():
    return {"status": "ok"}


@router.get("/api/auth/status")
async def api_auth_status(db: AsyncSession = Depends(get_db)):
    return {"registration_open": await auth.registration_open(db)}


@router.post("/api/register")
async def api_register(req: RegisterReq, request: Request, response: Response,
                       db: AsyncSession = Depends(get_db)):
    if not _register_limiter.allow(_client_ip(request)):
        raise HTTPException(429, "Слишком много попыток регистрации. Повторите позже.")
    if not await auth.registration_open(db):
        raise HTTPException(403, "Регистрация закрыта. Аккаунт заводит администратор.")
    token, err = await auth.register(db, req.username, req.password, req.full_name or "")
    if err:
        raise HTTPException(400, err)
    u = await repo.get_user_by_username(db, req.username.strip())
    if u:
        await repo.log_activity(db, u.id, "register", "Регистрация администратора")
    await db.commit()
    csrf = cookies.issue_csrf()               # #4 — токен в httpOnly-cookie + CSRF
    cookies.set_auth_cookies(response, token, csrf)
    return {"token": token, "csrf": csrf}


@router.post("/api/login")
async def api_login(req: LoginReq, request: Request, response: Response,
                    db: AsyncSession = Depends(get_db)):
    ip = _client_ip(request)
    uname = (req.username or "").strip()
    if not _login_limiter.allow(f"{ip}:{uname}"):
        log.warning("rate limit: login ip=%s user=%s", ip, uname)
        raise HTTPException(429, "Слишком много попыток входа. Повторите позже.")
    token, err = await auth.login(db, req.username, req.password)
    if err:
        # Issue #12 — фиксируем неуспешный вход (детекция брутфорса)
        u = await repo.get_user_by_username(db, uname)
        if u:
            await repo.log_activity(db, u.id, "login_failed", "Неуспешный вход")
            await db.commit()
        log.warning("failed login ip=%s user=%s", ip, uname)
        raise HTTPException(401, err)
    u = await repo.get_user_by_username(db, uname)
    if u:
        await repo.log_activity(db, u.id, "login", "Вход в систему")
    await db.commit()
    csrf = cookies.issue_csrf()               # #4 — токен в httpOnly-cookie + CSRF
    cookies.set_auth_cookies(response, token, csrf)
    return {"token": token, "csrf": csrf}


@router.get("/api/me")
async def api_me(user: dict = Depends(current_user)):
    return user


@router.post("/api/logout")
async def api_logout(response: Response, user: dict = Depends(current_user),
                     db: AsyncSession = Depends(get_db)):
    """Issue #4 — серверный выход: отзываем все токены пользователя (сдвиг версии) и
    чистим httpOnly-cookie, так что даже перехваченный токен перестаёт действовать сразу."""
    await repo.revoke_tokens(db, user["user_id"])
    await repo.log_activity(db, user["user_id"], "logout", "Выход из системы")
    await db.commit()
    cookies.clear_auth_cookies(response)
    return {"ok": True}


@router.post("/api/ticket")
async def api_ticket(user: dict = Depends(current_user)):
    """Issue #4 — одноразовый короткоживущий тикет для WebSocket (вместо JWT в URL)."""
    return {"ticket": tickets.issue(user["user_id"])}
