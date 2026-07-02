"""Cutover Стадия 3 — FastAPI-приложение на async-слое (PostgreSQL).

REST: авторизация, чаты, файлы, админка. WebSocket-чат и экспорт — Стадия 3b.
"""
import json

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth, storage
from app import repositories as repo
from app.config import get_settings
from app.database import SessionLocal, get_db, init_extensions
from app.orchestrator import orchestrator
from services import reports
from services.extract import detect_kind, extract_text

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

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
    # Сид дефолтной модели для шлюза, если реестр пуст.
    async with SessionLocal() as s:
        if not await repo.get_model_config_by_alias(s, settings.default_model):
            await repo.create_model_config(
                s, settings.default_model, "anthropic",
                settings.model, settings.fallback_model,
            )
            await s.commit()


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


class ModelConfigReq(BaseModel):
    alias: str
    provider: str
    endpoint: str | None = ""
    fallback_to: str | None = None


class AgentReq(BaseModel):
    name: str
    system_prompt: str | None = ""
    tools: list[str] | None = None
    default_model: int | None = None
    allowed_roles: str | None = ""


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


# ── Конструктор агентов: модели и агенты ──────────────────────────────────────

def _mc_dict(mc):
    return {"id": mc.id, "alias": mc.alias, "provider": mc.provider,
            "endpoint": mc.endpoint, "fallback_to": mc.fallback_to}


def _agent_dict(a):
    return {"id": a.id, "name": a.name, "system_prompt": a.system_prompt,
            "tools": a.tools or [], "default_model": a.default_model,
            "allowed_roles": a.allowed_roles}


@app.get("/api/admin/models")
async def api_admin_models(admin: dict = Depends(admin_user),
                           db: AsyncSession = Depends(get_db)):
    return [_mc_dict(m) for m in await repo.list_model_configs(db)]


@app.post("/api/admin/models")
async def api_admin_create_model(req: ModelConfigReq, admin: dict = Depends(admin_user),
                                 db: AsyncSession = Depends(get_db)):
    if await repo.get_model_config_by_alias(db, req.alias):
        raise HTTPException(400, "Модель с таким алиасом уже есть")
    mc = await repo.create_model_config(db, req.alias, req.provider,
                                        req.endpoint or "", req.fallback_to)
    await db.commit()
    return _mc_dict(mc)


@app.delete("/api/admin/models/{mc_id}")
async def api_admin_delete_model(mc_id: int, admin: dict = Depends(admin_user),
                                 db: AsyncSession = Depends(get_db)):
    await repo.delete_model_config(db, mc_id)
    await db.commit()
    return {"ok": True}


@app.get("/api/admin/agents")
async def api_admin_agents(admin: dict = Depends(admin_user),
                           db: AsyncSession = Depends(get_db)):
    return [_agent_dict(a) for a in await repo.list_agents(db)]


@app.post("/api/admin/agents")
async def api_admin_create_agent(req: AgentReq, admin: dict = Depends(admin_user),
                                 db: AsyncSession = Depends(get_db)):
    agent = await repo.create_agent(db, req.name, req.system_prompt or "",
                                    req.tools, req.default_model, req.allowed_roles or "")
    await db.commit()
    return _agent_dict(agent)


@app.delete("/api/admin/agents/{agent_id}")
async def api_admin_delete_agent(agent_id: int, admin: dict = Depends(admin_user),
                                 db: AsyncSession = Depends(get_db)):
    await repo.delete_agent(db, agent_id)
    await db.commit()
    return {"ok": True}


# ── Экспорт отчётов ──────────────────────────────────────────────────────────

async def _report_data(db) -> dict:
    return {"totals": await repo.admin_overview(db),
            "users": await repo.admin_user_stats(db),
            "per_day": await repo.messages_per_day(db, 14),
            "activity": await repo.activity_log_list(db, limit=300)}


@app.get("/api/admin/export/xlsx")
async def api_admin_export_xlsx(admin: dict = Depends(admin_user),
                                db: AsyncSession = Depends(get_db)):
    data = reports.build_xlsx(await _report_data(db))
    return Response(content=data, media_type=_XLSX_MIME,
                    headers={"Content-Disposition": 'attachment; filename="report.xlsx"'})


@app.get("/api/admin/export/docx")
async def api_admin_export_docx(admin: dict = Depends(admin_user),
                                db: AsyncSession = Depends(get_db)):
    data = reports.build_docx(await _report_data(db))
    return Response(content=data, media_type=_DOCX_MIME,
                    headers={"Content-Disposition": 'attachment; filename="report.docx"'})


@app.get("/api/admin/users/{uid}/export/docx")
async def api_admin_export_user_docx(uid: int, admin: dict = Depends(admin_user),
                                     db: AsyncSession = Depends(get_db)):
    user = await repo.get_user(db, uid)
    if not user:
        raise HTTPException(404, "Сотрудник не найден")
    convs_meta = await repo.admin_conversations(db, uid)
    convs = []
    for c in convs_meta:
        items = await repo.load_history(db, c["id"], limit=1000)
        convs.append({"title": c["title"], "updated_at": c["updated_at"],
                      "count": c["messages"], "items": items})
    user_dict = {"full_name": user.full_name, "username": user.username, "role": user.role}
    data = reports.build_user_docx(user_dict, convs)
    return Response(content=data, media_type=_DOCX_MIME,
                    headers={"Content-Disposition": 'attachment; filename="user_chats.docx"'})


# ── WebSocket-чат ────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_chat(ws: WebSocket):
    token = ws.query_params.get("token", "")
    user = auth.verify(token)
    if not user:
        await ws.close(code=4401)
        return
    await ws.accept()
    uid = user["user_id"]

    async def emit(event: dict):
        await ws.send_text(json.dumps(event, ensure_ascii=False))

    try:
        while True:
            msg = json.loads(await ws.receive_text())
            text = msg.get("text", "")
            conversation_id = msg.get("conversation_id")
            file_ids = msg.get("file_ids", [])

            async with SessionLocal() as s:
                if not conversation_id:
                    conv = await repo.create_conversation(s, uid, (text or "Новый чат")[:60])
                    await s.commit()
                    conversation_id = conv.id
                    await emit({"type": "conversation", "id": conversation_id, "title": conv.title})
                else:
                    conv = await repo.get_conversation(s, conversation_id)
                    if not conv or conv.user_id != uid:
                        await emit({"type": "error", "text": "Чат не найден или недоступен"})
                        continue

                # вложения — только свои файлы (защита от IDOR)
                attachments = []
                for fid in file_ids:
                    rec = await repo.get_file_record(s, fid)
                    if not rec or rec.user_id != uid:
                        continue
                    res = storage.read_record_bytes(rec)
                    if not res:
                        continue
                    data, name = res
                    kind = detect_kind(name)
                    txt = "" if kind == "image" else extract_text(data, name)
                    attachments.append({"kind": kind, "name": name, "data": data, "text": txt})

            await orchestrator.process(conversation_id, uid, text, attachments, emit)
    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await emit({"type": "error", "text": f"Сбой: {e}"})
        except Exception:
            pass
