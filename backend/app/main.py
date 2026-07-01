"""Cutover Стадия 3 — FastAPI-приложение на async-слое (PostgreSQL).

REST: авторизация, чаты, файлы, админка. WebSocket-чат и экспорт — Стадия 3b.
"""
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth
from app import repositories as repo
from app import storage
from app.config import get_settings
from app.database import get_db, init_extensions
from services.extract import detect_kind

settings = get_settings()
app = FastAPI(title="Remtechnika AI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_bearer = HTTPBearer(auto_error=False)


@app.on_event("startup")
async def _startup():
    await init_extensions()


# ── auth dependencies ────────────────────────────────────────────────────────

def current_user(cred: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    if not cred:
        raise HTTPException(401, "Не авторизован")
    user = auth.verify(cred.credentials)
    if not user:
        raise HTTPException(401, "Неверный или истёкший токен")
    return user


def admin_user(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(403, "Доступ только для администратора")
    return user


# ── models ────────────────────────────────────────────────────────────────────

class LoginReq(BaseModel):
    username: str
    password: str


class RegisterReq(BaseModel):
    username: str
    password: str
    full_name: str | None = ""


class NewConversationReq(BaseModel):
    title: str | None = None


class AdminCreateUserReq(BaseModel):
    username: str
    password: str
    full_name: str | None = ""
    role: str = "user"


class PasswordReq(BaseModel):
    password: str


# ── auth / регистрация ─────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/auth/status")
async def api_auth_status(db: AsyncSession = Depends(get_db)):
    return {"registration_open": await auth.registration_open(db)}


@app.post("/api/register")
async def api_register(req: RegisterReq, db: AsyncSession = Depends(get_db)):
    if not await auth.registration_open(db):
        raise HTTPException(403, "Регистрация закрыта. Аккаунт заводит администратор.")
    token, err = await auth.register(db, req.username, req.password, req.full_name or "")
    if err:
        raise HTTPException(400, err)
    u = await repo.get_user_by_username(db, req.username.strip())
    if u:
        await repo.log_activity(db, u.id, "register", "Регистрация администратора")
    await db.commit()
    return {"token": token}


@app.post("/api/login")
async def api_login(req: LoginReq, db: AsyncSession = Depends(get_db)):
    token, err = await auth.login(db, req.username, req.password)
    if err:
        raise HTTPException(401, err)
    u = await repo.get_user_by_username(db, req.username.strip())
    if u:
        await repo.log_activity(db, u.id, "login", "Вход в систему")
    await db.commit()
    return {"token": token}


@app.get("/api/me")
async def api_me(user: dict = Depends(current_user)):
    return user


# ── conversations ──────────────────────────────────────────────────────────────

def _conv_dict(c):
    return {"id": c.id, "title": c.title,
            "created_at": repo._iso(c.created_at), "updated_at": repo._iso(c.updated_at)}


@app.get("/api/conversations")
async def api_conversations(user: dict = Depends(current_user),
                            db: AsyncSession = Depends(get_db)):
    return [_conv_dict(c) for c in await repo.list_conversations(db, user["user_id"])]


@app.post("/api/conversations")
async def api_new_conversation(req: NewConversationReq, user: dict = Depends(current_user),
                               db: AsyncSession = Depends(get_db)):
    conv = await repo.create_conversation(db, user["user_id"], req.title or "Новый чат")
    await db.commit()
    return _conv_dict(conv)


@app.delete("/api/conversations/{conversation_id}")
async def api_delete_conversation(conversation_id: int, user: dict = Depends(current_user),
                                  db: AsyncSession = Depends(get_db)):
    conv = await repo.get_conversation(db, conversation_id)
    if not conv or conv.user_id != user["user_id"]:
        raise HTTPException(404, "Чат не найден")
    await repo.delete_conversation(db, conversation_id, user["user_id"])
    await db.commit()
    return {"ok": True}


@app.get("/api/conversations/{conversation_id}/messages")
async def api_messages(conversation_id: int, user: dict = Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    conv = await repo.get_conversation(db, conversation_id)
    if not conv or conv.user_id != user["user_id"]:
        raise HTTPException(404, "Чат не найден")
    return await repo.load_history(db, conversation_id, limit=200)


# ── files ──────────────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...), conversation_id: int | None = Form(None),
                     user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    data = await file.read()
    kind = detect_kind(file.filename)
    rec = await storage.save_bytes(db, user["user_id"], conversation_id, file.filename,
                                   data, kind=kind, direction="upload")
    await db.commit()
    return {"file_id": rec.id, "name": file.filename, "kind": kind}


@app.get("/api/files/{file_id}")
async def api_download(file_id: int, token: str = "", db: AsyncSession = Depends(get_db)):
    u = auth.verify(token) if token else None
    if not u:
        raise HTTPException(401, "Не авторизован")
    rec = await repo.get_file_record(db, file_id)
    if not rec:
        raise HTTPException(404, "Файл не найден")
    if rec.user_id != u["user_id"] and u.get("role") != "admin":
        raise HTTPException(403, "Нет доступа к файлу")
    res = storage.read_record_bytes(rec)
    if not res:
        raise HTTPException(404, "Файл не найден")
    data, name = res
    return Response(content=data, media_type="application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ── admin ────────────────────────────────────────────────────────────────────

@app.get("/api/admin/overview")
async def api_admin_overview(admin: dict = Depends(admin_user),
                             db: AsyncSession = Depends(get_db)):
    return {"totals": await repo.admin_overview(db),
            "per_day": await repo.messages_per_day(db, 14),
            "users": await repo.admin_user_stats(db)}


@app.get("/api/admin/users")
async def api_admin_users(admin: dict = Depends(admin_user),
                          db: AsyncSession = Depends(get_db)):
    return await repo.admin_user_stats(db)


@app.post("/api/admin/users")
async def api_admin_create_user(req: AdminCreateUserReq, admin: dict = Depends(admin_user),
                                db: AsyncSession = Depends(get_db)):
    user, err = await auth.admin_create_user(db, req.username, req.password,
                                             req.full_name or "", req.role)
    if err:
        raise HTTPException(400, err)
    await repo.log_activity(db, admin["user_id"], "create_user", f"Создан аккаунт {req.username}")
    await db.commit()
    return {"id": user.id, "username": user.username, "role": user.role}


@app.post("/api/admin/users/{uid}/password")
async def api_admin_reset_password(uid: int, req: PasswordReq, admin: dict = Depends(admin_user),
                                   db: AsyncSession = Depends(get_db)):
    if not await repo.get_user(db, uid):
        raise HTTPException(404, "Сотрудник не найден")
    if len(req.password) < 4:
        raise HTTPException(400, "Пароль слишком короткий (минимум 4 символа)")
    await repo.update_password(db, uid, auth.hash_password(req.password))
    await repo.log_activity(db, admin["user_id"], "reset_password", f"Сброшен пароль (id {uid})")
    await db.commit()
    return {"ok": True}


@app.post("/api/admin/users/{uid}/active")
async def api_admin_set_active(uid: int, active: bool, admin: dict = Depends(admin_user),
                               db: AsyncSession = Depends(get_db)):
    if uid == admin["user_id"]:
        raise HTTPException(400, "Нельзя деактивировать самого себя")
    await repo.set_user_active(db, uid, active)
    await db.commit()
    return {"ok": True}


@app.get("/api/admin/users/{uid}/conversations")
async def api_admin_user_conversations(uid: int, admin: dict = Depends(admin_user),
                                       db: AsyncSession = Depends(get_db)):
    user = await repo.get_user(db, uid)
    if not user:
        raise HTTPException(404, "Сотрудник не найден")
    return {"user": {"id": user.id, "username": user.username,
                     "full_name": user.full_name, "role": user.role},
            "conversations": await repo.admin_conversations(db, uid)}


@app.get("/api/admin/conversations/{cid}/messages")
async def api_admin_conversation_messages(cid: int, admin: dict = Depends(admin_user),
                                          db: AsyncSession = Depends(get_db)):
    conv = await repo.get_conversation(db, cid)
    if not conv:
        raise HTTPException(404, "Чат не найден")
    return {"conversation": _conv_dict(conv),
            "messages": await repo.load_history(db, cid, limit=500)}


@app.get("/api/admin/activity")
async def api_admin_activity(limit: int = 200, user_id: int | None = None,
                             admin: dict = Depends(admin_user),
                             db: AsyncSession = Depends(get_db)):
    return await repo.activity_log_list(db, limit=limit, user_id=user_id)
