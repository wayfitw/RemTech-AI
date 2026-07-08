"""Cutover Стадия 3 — FastAPI-приложение на async-слое (PostgreSQL).

REST: авторизация, чаты, файлы, админка. WebSocket-чат и экспорт — Стадия 3b.
"""
import json
from contextlib import asynccontextmanager

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agent.registry import tool_options
from app import auth, kb, storage
from app import repositories as repo
from app.config import get_settings
from app.database import SessionLocal, get_db, init_extensions
from app.embeddings import get_embedder
from app.logging_config import get_logger, setup_logging
from app.orchestrator import orchestrator
from app.ratelimit import RateLimiter
from services import filecheck, reports
from services.extract import detect_kind, extract_text

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

settings = get_settings()
setup_logging(settings.log_level)
log = get_logger("remtech.api")
_MAX_UPLOAD = settings.max_upload_mb * 1024 * 1024

# Issue #3 — лимиты частоты для чувствительных эндпоинтов (in-memory, на процесс).
_login_limiter = RateLimiter(max_events=10, window_seconds=300)     # вход: 10 / 5 мин на ip+логин
_register_limiter = RateLimiter(max_events=5, window_seconds=3600)  # регистрация: 5 / час на ip
_ws_limiter = RateLimiter(max_events=30, window_seconds=60)         # сообщения ws: 30 / мин на пользователя

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # #18 — современный lifespan вместо устаревшего @app.on_event.
    await init_extensions()
    # Сид моделей шлюза: основная (claude) + реальный резерв (claude-fast, тот же
    # провайдер, быстрая модель) — issue #21. Yandex/vLLM-провайдеры — стадия 2b.
    async with SessionLocal() as s:
        if not await repo.get_model_config_by_alias(s, settings.default_model):
            if not await repo.get_model_config_by_alias(s, settings.fallback_model):
                await repo.create_model_config(
                    s, settings.fallback_model, "anthropic", settings.model_fast, None)
            await repo.create_model_config(
                s, settings.default_model, "anthropic",
                settings.model, settings.fallback_model)
            await s.commit()
    yield


app = FastAPI(title="Remtechnika AI", lifespan=lifespan)
# CORS: только явный whitelist источников; без фолбэка на "*".
# JWT передаётся в заголовке Authorization, cookie не используются →
# allow_credentials=False (небезопасная связка "* + credentials" исключена).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_bearer = HTTPBearer(auto_error=False)


# ── auth dependencies ────────────────────────────────────────────────────────

async def _user_from_token(token: str, db: AsyncSession) -> dict | None:
    """Issue #4 — проверка токена со сверкой active/роли по БД, чтобы деактивация
    и смена роли действовали немедленно, а не до истечения JWT."""
    claims = auth.verify(token or "")
    if not claims:
        return None
    u = await repo.get_user(db, claims["user_id"])
    if not u or not u.active:
        return None
    return {"user_id": u.id, "username": u.username,
            "name": u.full_name or u.username, "role": u.role}


async def current_user(cred: HTTPAuthorizationCredentials = Depends(_bearer),
                       db: AsyncSession = Depends(get_db)) -> dict:
    if not cred:
        raise HTTPException(401, "Не авторизован")
    user = await _user_from_token(cred.credentials, db)
    if not user:
        raise HTTPException(401, "Неверный токен или аккаунт деактивирован")
    return user


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


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "?"


@app.post("/api/register")
async def api_register(req: RegisterReq, request: Request, db: AsyncSession = Depends(get_db)):
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
    return {"token": token}


@app.post("/api/login")
async def api_login(req: LoginReq, request: Request, db: AsyncSession = Depends(get_db)):
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
            # IP не пишем в журнал (виден админам) — он остаётся в серверных логах ниже
            await repo.log_activity(db, u.id, "login_failed", "Неуспешный вход")
            await db.commit()
        log.warning("failed login ip=%s user=%s", ip, uname)
        raise HTTPException(401, err)
    u = await repo.get_user_by_username(db, uname)
    if u:
        await repo.log_activity(db, u.id, "login", "Вход в систему")
    await db.commit()
    return {"token": token}


@app.get("/api/me")
async def api_me(user: dict = Depends(current_user)):
    return user


@app.get("/api/agents")
async def api_agents(user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Агенты (модули), доступные пользователю по его роли."""
    role = user.get("role", "user")
    out = []
    for a in await repo.list_agents(db):
        if role_can_use_agent(role, a):
            out.append({"id": a.id, "name": a.name})
    return out


# ── conversations ──────────────────────────────────────────────────────────────

def _conv_dict(c):
    return {"id": c.id, "title": c.title,
            "created_at": repo.iso(c.created_at), "updated_at": repo.iso(c.updated_at)}


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
    data = await _read_upload_limited(file)
    if err := filecheck.ensure_allowed(file.filename, data):
        raise HTTPException(400, err)
    kind = detect_kind(file.filename)
    rec = await storage.save_bytes(db, user["user_id"], conversation_id, file.filename,
                                   data, kind=kind, direction="upload")
    await db.commit()
    return {"file_id": rec.id, "name": file.filename, "kind": kind}


@app.get("/api/files/{file_id}")
async def api_download(file_id: int, token: str = "", db: AsyncSession = Depends(get_db)):
    u = await _user_from_token(token, db) if token else None
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
                    headers={"Content-Disposition": filecheck.content_disposition(name)})


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
    if err := auth.validate_password(req.password):
        raise HTTPException(400, err)
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
    await repo.log_activity(db, admin["user_id"], "set_active",
                            f"{'Активирован' if active else 'Деактивирован'} аккаунт (id {uid})")
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
    if conv.user_id != admin["user_id"]:
        await repo.log_activity(db, admin["user_id"], "admin_view_chat",
                                f"Просмотр чужого чата (id {cid})")
        await db.commit()
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
    await repo.log_activity(db, admin["user_id"], "delete_model", f"Удалена модель (id {mc_id})")
    await db.commit()
    return {"ok": True}


@app.get("/api/admin/tools")
async def api_admin_tools(admin: dict = Depends(admin_user)):
    """Инструменты для конструктора агентов — единый источник (issue #18)."""
    return tool_options()


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
    await repo.log_activity(db, admin["user_id"], "delete_agent", f"Удалён агент (id {agent_id})")
    await db.commit()
    return {"ok": True}


# ── База знаний (только admin) ────────────────────────────────────────────────

def embedder_dep():
    return get_embedder()


@app.post("/api/admin/kb/upload")
async def api_admin_kb_upload(file: UploadFile = File(...),
                              owner_role: str | None = Form(None),
                              admin: dict = Depends(admin_user),
                              db: AsyncSession = Depends(get_db),
                              embedder=Depends(embedder_dep)):
    data = await _read_upload_limited(file)
    if err := filecheck.ensure_allowed(file.filename, data):
        raise HTTPException(400, err)
    # для БЗ берём больший лимит текста — длинные документы не теряют хвост (аудит БЗ)
    text = extract_text(data, file.filename, max_chars=settings.kb_extract_max_chars)
    if not text.strip():
        raise HTTPException(400, "Не удалось извлечь текст из документа")

    # Документ создаём сразу; тяжёлый чанкинг+эмбеддинги — вне HTTP-запроса (issue #22).
    doc = await repo.create_kb_document(db, file.filename, "upload", owner_role or None)
    await repo.log_activity(db, admin["user_id"], "kb_upload", file.filename)
    await db.commit()

    if settings.kb_async_ingest:
        from app.tasks import ingest_document_task
        ingest_document_task.delay(doc.id, text)
        return {"document_id": doc.id, "file_name": file.filename, "status": "processing"}

    n = await kb.ingest_chunks(db, embedder, doc.id, text)
    await db.commit()
    return {"document_id": doc.id, "file_name": file.filename, "chunks": n, "status": "ready"}


@app.get("/api/admin/kb")
async def api_admin_kb_list(admin: dict = Depends(admin_user),
                            db: AsyncSession = Depends(get_db)):
    return await repo.list_kb_documents(db)


@app.delete("/api/admin/kb/{document_id}")
async def api_admin_kb_delete(document_id: int, admin: dict = Depends(admin_user),
                              db: AsyncSession = Depends(get_db)):
    await repo.delete_kb_document(db, document_id)
    await repo.log_activity(db, admin["user_id"], "kb_delete", f"Удалён документ БЗ (id {document_id})")
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
    await repo.log_activity(db, admin["user_id"], "export", "Экспорт отчёта (xlsx)")
    await db.commit()
    return Response(content=data, media_type=_XLSX_MIME,
                    headers={"Content-Disposition": 'attachment; filename="report.xlsx"'})


@app.get("/api/admin/export/docx")
async def api_admin_export_docx(admin: dict = Depends(admin_user),
                                db: AsyncSession = Depends(get_db)):
    data = reports.build_docx(await _report_data(db))
    await repo.log_activity(db, admin["user_id"], "export", "Экспорт отчёта (docx)")
    await db.commit()
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
    await repo.log_activity(db, admin["user_id"], "export", f"Экспорт чатов сотрудника (id {uid})")
    await db.commit()
    return Response(content=data, media_type=_DOCX_MIME,
                    headers={"Content-Disposition": 'attachment; filename="user_chats.docx"'})


# ── WebSocket-чат ────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_chat(ws: WebSocket):
    token = ws.query_params.get("token", "")
    async with SessionLocal() as s:
        user = await _user_from_token(token, s)   # #4 — сверка active/роли по БД
    if not user:
        await ws.close(code=4401)
        return
    await ws.accept()
    uid = user["user_id"]

    async def emit(event: dict):
        await ws.send_text(json.dumps(event, ensure_ascii=False))

    while True:
        # Issue #15 — одна битая рамка/ошибка кадра не рвёт всю WS-сессию.
        try:
            raw = await ws.receive_text()
        except WebSocketDisconnect:
            return
        try:
            msg = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            await emit({"type": "error", "text": "Некорректный формат сообщения"})
            continue

        # Issue #3 — лимит частоты сообщений на пользователя
        if not _ws_limiter.allow(str(uid)):
            await emit({"type": "error", "text": "Слишком часто. Подождите немного."})
            continue

        try:
            text = msg.get("text", "")
            conversation_id = msg.get("conversation_id")
            file_ids = msg.get("file_ids", [])
            agent_id = msg.get("agent_id")

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

                # RBAC: роль обязана иметь доступ к выбранному агенту (не только в листинге)
                if agent_id is not None:
                    agent = await repo.get_agent(s, agent_id)
                    if not agent:
                        await emit({"type": "error", "text": "Агент не найден"})
                        continue
                    if not role_can_use_agent(user.get("role", "user"), agent):
                        await emit({"type": "error", "text": "Недостаточно прав для этого агента"})
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

            # админ видит всю базу знаний (roles=None), сотрудник — по своей роли
            roles = None if user.get("role") == "admin" else [user.get("role", "user")]
            await orchestrator.process(conversation_id, uid, text, attachments, emit, roles, agent_id)
        except WebSocketDisconnect:
            return
        except Exception:
            # #15 — причину логируем на сервере, клиенту отдаём обобщённо (без внутренних деталей)
            log.exception("ws message handling failed uid=%s", uid)
            try:
                await emit({"type": "error", "text": "Внутренняя ошибка обработки запроса"})
            except Exception:
                return
