"""FastAPI-приложение: REST + WebSocket-чат. Этап 1 — веб-оболочка mybot."""
import json

from fastapi import (
    Depends, FastAPI, File, Form, HTTPException, UploadFile, WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

import auth
import db
import storage
from agent.orchestrator import orchestrator
from config import CORS_ORIGINS
from services import extract

app = FastAPI(title="Remtechnika AI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_bearer = HTTPBearer(auto_error=False)


@app.on_event("startup")
def _startup():
    db.init_db()


# ── auth dependency ──────────────────────────────────────────────────────────

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


# ── REST ──────────────────────────────────────────────────────────────────────

@app.post("/api/register")
def api_register(req: RegisterReq):
    token, err = auth.register(req.username, req.password, req.full_name or "")
    if err:
        raise HTTPException(400, err)
    u = db.get_user_by_username(req.username.strip())
    if u:
        db.log_activity(u["id"], "register", "Регистрация аккаунта")
    return {"token": token}


@app.post("/api/login")
def api_login(req: LoginReq):
    token, err = auth.login(req.username, req.password)
    if err:
        raise HTTPException(401, err)
    u = db.get_user_by_username(req.username.strip())
    if u:
        db.log_activity(u["id"], "login", "Вход в систему")
    return {"token": token}


@app.get("/api/me")
def api_me(user: dict = Depends(current_user)):
    return user


# ── Admin (только для роли admin) ─────────────────────────────────────────────

@app.get("/api/admin/overview")
def api_admin_overview(admin: dict = Depends(admin_user)):
    return {
        "totals": db.admin_overview(),
        "per_day": db.messages_per_day(14),
        "users": db.admin_user_stats(),
    }


@app.get("/api/admin/users")
def api_admin_users(admin: dict = Depends(admin_user)):
    return db.admin_user_stats()


@app.get("/api/admin/users/{uid}/conversations")
def api_admin_user_conversations(uid: int, admin: dict = Depends(admin_user)):
    user = db.get_user(uid)
    if not user:
        raise HTTPException(404, "Сотрудник не найден")
    return {
        "user": {"id": user["id"], "username": user["username"],
                 "full_name": user.get("full_name"), "role": user["role"]},
        "conversations": db.admin_conversations(uid),
    }


@app.get("/api/admin/conversations/{cid}/messages")
def api_admin_conversation_messages(cid: int, admin: dict = Depends(admin_user)):
    conv = db.get_conversation(cid)
    if not conv:
        raise HTTPException(404, "Чат не найден")
    return {"conversation": conv, "messages": db.load_history(cid, limit=500)}


@app.get("/api/admin/activity")
def api_admin_activity(limit: int = 200, user_id: int | None = None,
                       admin: dict = Depends(admin_user)):
    return db.activity_log_list(limit=limit, user_id=user_id)


@app.post("/api/admin/users/{uid}/active")
def api_admin_set_active(uid: int, active: bool, admin: dict = Depends(admin_user)):
    if uid == admin["user_id"]:
        raise HTTPException(400, "Нельзя деактивировать самого себя")
    db.set_user_active(uid, active)
    return {"ok": True}


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@app.get("/api/admin/export/xlsx")
def api_admin_export_xlsx(admin: dict = Depends(admin_user)):
    from services import reports
    data = reports.build_xlsx()
    return Response(content=data, media_type=_XLSX_MIME, headers={
        "Content-Disposition": 'attachment; filename="report.xlsx"'})


@app.get("/api/admin/export/docx")
def api_admin_export_docx(admin: dict = Depends(admin_user)):
    from services import reports
    data = reports.build_docx()
    return Response(content=data, media_type=_DOCX_MIME, headers={
        "Content-Disposition": 'attachment; filename="report.docx"'})


@app.get("/api/admin/users/{uid}/export/docx")
def api_admin_export_user_docx(uid: int, admin: dict = Depends(admin_user)):
    from services import reports
    if not db.get_user(uid):
        raise HTTPException(404, "Сотрудник не найден")
    data = reports.build_user_docx(uid)
    return Response(content=data, media_type=_DOCX_MIME, headers={
        "Content-Disposition": 'attachment; filename="user_chats.docx"'})


@app.get("/api/conversations")
def api_conversations(user: dict = Depends(current_user)):
    return db.list_conversations(user["user_id"])


@app.post("/api/conversations")
def api_new_conversation(req: NewConversationReq, user: dict = Depends(current_user)):
    return db.create_conversation(user["user_id"], req.title or "Новый чат")


@app.delete("/api/conversations/{conversation_id}")
def api_delete_conversation(conversation_id: int, user: dict = Depends(current_user)):
    conv = db.get_conversation(conversation_id)
    if not conv or conv["user_id"] != user["user_id"]:
        raise HTTPException(404, "Чат не найден")
    db.delete_conversation(conversation_id, user["user_id"])
    return {"ok": True}


@app.get("/api/conversations/{conversation_id}/messages")
def api_messages(conversation_id: int, user: dict = Depends(current_user)):
    conv = db.get_conversation(conversation_id)
    if not conv or conv["user_id"] != user["user_id"]:
        raise HTTPException(404, "Чат не найден")
    return db.load_history(conversation_id, limit=200)


@app.post("/api/upload")
async def api_upload(
    file: UploadFile = File(...),
    conversation_id: int | None = Form(None),
    user: dict = Depends(current_user),
):
    data = await file.read()
    kind = extract.detect_kind(file.filename)
    fid = storage.save_bytes(
        user["user_id"], conversation_id, file.filename, data,
        kind=kind, direction="upload",
    )
    return {"file_id": fid, "name": file.filename, "kind": kind}


@app.get("/api/files/{file_id}")
def api_download(file_id: int, token: str = ""):
    # Скачивание: токен передаётся через query (?token=) для прямых ссылок.
    u = auth.verify(token) if token else None
    if not u:
        raise HTTPException(401, "Не авторизован")
    res = storage.read_bytes(file_id)
    if not res:
        raise HTTPException(404, "Файл не найден")
    data, name = res
    headers = {"Content-Disposition": f'attachment; filename="{name}"'}
    return Response(content=data, media_type="application/octet-stream", headers=headers)


# ── WebSocket чат ────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def ws_chat(ws: WebSocket):
    token = ws.query_params.get("token", "")
    user = auth.verify(token)
    if not user:
        await ws.close(code=4401)
        return
    await ws.accept()

    async def emit(event: dict):
        await ws.send_text(json.dumps(event, ensure_ascii=False))

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            text = msg.get("text", "")
            conversation_id = msg.get("conversation_id")
            file_ids = msg.get("file_ids", [])

            if not conversation_id:
                conv = db.create_conversation(user["user_id"], (text or "Новый чат")[:60])
                conversation_id = conv["id"]
                await emit({"type": "conversation", "id": conversation_id, "title": conv["title"]})

            # Резолвим вложения: читаем байты, извлекаем текст
            attachments = []
            for fid in file_ids:
                res = storage.read_bytes(fid)
                if not res:
                    continue
                data, name = res
                kind = extract.detect_kind(name)
                txt = "" if kind == "image" else extract.extract_text(data, name)
                attachments.append({"kind": kind, "name": name, "data": data, "text": txt})

            await orchestrator.process(conversation_id, user["user_id"], text, attachments, emit)
    except WebSocketDisconnect:
        return
    except Exception as e:
        try:
            await emit({"type": "error", "text": f"Сбой: {e}"})
        except Exception:
            pass


@app.get("/api/health")
def health():
    return {"status": "ok"}
