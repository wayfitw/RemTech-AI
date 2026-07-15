"""Роутер чатов: список агентов пользователя, диалоги, история."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app import repositories as repo
from app.database import get_db
from app.deps import conv_dict, current_user, role_can_use_agent
from app.schemas import NewConversationReq

router = APIRouter()


@router.get("/api/agents")
async def api_agents(user: dict = Depends(current_user), db: AsyncSession = Depends(get_db)):
    """Агенты (модули), доступные пользователю по его роли."""
    role = user.get("role", "user")
    return [{"id": a.id, "name": a.name}
            for a in await repo.list_agents(db) if role_can_use_agent(role, a)]


@router.get("/api/conversations")
async def api_conversations(user: dict = Depends(current_user),
                            db: AsyncSession = Depends(get_db)):
    return [conv_dict(c) for c in await repo.list_conversations(db, user["user_id"])]


@router.get("/api/notifications")
async def api_notifications(user: dict = Depends(current_user),
                            db: AsyncSession = Depends(get_db)):
    """Issue #37 — лента уведомлений о тендерах для роли пользователя (admin — все)."""
    items = await repo.list_notifications(db, user.get("role", "user"))
    return [{"id": n.id, "title": n.title, "body": n.body, "link": n.link,
             "created_at": repo.iso(n.created_at)} for n in items]


@router.post("/api/conversations")
async def api_new_conversation(req: NewConversationReq, user: dict = Depends(current_user),
                               db: AsyncSession = Depends(get_db)):
    conv = await repo.create_conversation(db, user["user_id"], req.title or "Новый чат")
    await db.commit()
    return conv_dict(conv)


@router.delete("/api/conversations/{conversation_id}")
async def api_delete_conversation(conversation_id: int, user: dict = Depends(current_user),
                                  db: AsyncSession = Depends(get_db)):
    conv = await repo.get_conversation(db, conversation_id)
    if not conv or conv.user_id != user["user_id"]:
        raise HTTPException(404, "Чат не найден")
    await repo.delete_conversation(db, conversation_id, user["user_id"])
    await db.commit()
    return {"ok": True}


@router.get("/api/conversations/{conversation_id}/messages")
async def api_messages(conversation_id: int, user: dict = Depends(current_user),
                       db: AsyncSession = Depends(get_db)):
    conv = await repo.get_conversation(db, conversation_id)
    if not conv or conv.user_id != user["user_id"]:
        raise HTTPException(404, "Чат не найден")
    return await repo.load_history(db, conversation_id, limit=200)


@router.get("/api/conversations/{conversation_id}/files")
async def api_conversation_files(conversation_id: int, user: dict = Depends(current_user),
                                 db: AsyncSession = Depends(get_db)):
    """Сгенерированные файлы беседы — для восстановления кнопок скачивания при
    переоткрытии чата (в истории нет привязки файла к сообщению)."""
    conv = await repo.get_conversation(db, conversation_id)
    if not conv or conv.user_id != user["user_id"]:
        raise HTTPException(404, "Чат не найден")
    return [{"id": f.id, "name": f.file_name}
            for f in await repo.list_output_files(db, conversation_id)]
