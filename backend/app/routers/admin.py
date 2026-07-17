"""Роутер администрирования: статистика, сотрудники, модели, агенты, экспорт."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from agent.registry import tool_options
from app import auth
from app import repositories as repo
from app.database import get_db
from app.deps import admin_user, conv_dict
from app.schemas import (
    AdminCreateUserReq,
    AgentReq,
    ModelConfigReq,
    PasswordReq,
    TenderSubscriptionReq,
)
from services import reports

router = APIRouter(prefix="/api/admin")

_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _mc_dict(mc):
    return {"id": mc.id, "alias": mc.alias, "provider": mc.provider,
            "endpoint": mc.endpoint, "fallback_to": mc.fallback_to}


def _agent_dict(a):
    return {"id": a.id, "name": a.name, "system_prompt": a.system_prompt,
            "tools": a.tools or [], "default_model": a.default_model,
            "allowed_roles": a.allowed_roles}


async def _report_data(db) -> dict:
    return {"totals": await repo.admin_overview(db),
            "users": await repo.admin_user_stats(db),
            "per_day": await repo.messages_per_day(db, 14),
            "activity": await repo.activity_log_list(db, limit=300)}


# ── Статистика и сотрудники ────────────────────────────────────────────────────

@router.get("/overview")
async def api_admin_overview(admin: dict = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    return {"totals": await repo.admin_overview(db),
            "per_day": await repo.messages_per_day(db, 14),
            "users": await repo.admin_user_stats(db)}


@router.get("/users")
async def api_admin_users(admin: dict = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    return await repo.admin_user_stats(db)


@router.post("/users")
async def api_admin_create_user(req: AdminCreateUserReq, admin: dict = Depends(admin_user),
                                db: AsyncSession = Depends(get_db)):
    user, err = await auth.admin_create_user(db, req.username, req.password,
                                             req.full_name or "", req.role)
    if err:
        raise HTTPException(400, err)
    await repo.log_activity(db, admin["user_id"], "create_user", f"Создан аккаунт {req.username}")
    await db.commit()
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/users/{uid}/password")
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


@router.post("/users/{uid}/active")
async def api_admin_set_active(uid: int, active: bool, admin: dict = Depends(admin_user),
                               db: AsyncSession = Depends(get_db)):
    if uid == admin["user_id"]:
        raise HTTPException(400, "Нельзя деактивировать самого себя")
    await repo.set_user_active(db, uid, active)
    if not active:
        await repo.revoke_tokens(db, uid)   # issue #4 — деактивация сразу гасит токены
    await repo.log_activity(db, admin["user_id"], "set_active",
                            f"{'Активирован' if active else 'Деактивирован'} аккаунт (id {uid})")
    await db.commit()
    return {"ok": True}


@router.post("/users/{uid}/logout")
async def api_admin_force_logout(uid: int, admin: dict = Depends(admin_user),
                                 db: AsyncSession = Depends(get_db)):
    """Issue #4 — форс-разлогин: отзываем все токены пользователя (напр. при
    компрометации сессии), без деактивации и смены пароля."""
    if not await repo.get_user(db, uid):
        raise HTTPException(404, "Сотрудник не найден")
    await repo.revoke_tokens(db, uid)
    await repo.log_activity(db, admin["user_id"], "force_logout", f"Отзыв сессий (id {uid})")
    await db.commit()
    return {"ok": True}


@router.get("/users/{uid}/conversations")
async def api_admin_user_conversations(uid: int, admin: dict = Depends(admin_user),
                                       db: AsyncSession = Depends(get_db)):
    user = await repo.get_user(db, uid)
    if not user:
        raise HTTPException(404, "Сотрудник не найден")
    return {"user": {"id": user.id, "username": user.username,
                     "full_name": user.full_name, "role": user.role},
            "conversations": await repo.admin_conversations(db, uid)}


@router.get("/conversations/{cid}/messages")
async def api_admin_conversation_messages(cid: int, admin: dict = Depends(admin_user),
                                          db: AsyncSession = Depends(get_db)):
    conv = await repo.get_conversation(db, cid)
    if not conv:
        raise HTTPException(404, "Чат не найден")
    if conv.user_id != admin["user_id"]:
        await repo.log_activity(db, admin["user_id"], "admin_view_chat",
                                f"Просмотр чужого чата (id {cid})")
        await db.commit()
    return {"conversation": conv_dict(conv),
            "messages": await repo.load_history(db, cid, limit=500)}


@router.get("/activity")
async def api_admin_activity(limit: int = 200, user_id: int | None = None,
                             admin: dict = Depends(admin_user),
                             db: AsyncSession = Depends(get_db)):
    return await repo.activity_log_list(db, limit=limit, user_id=user_id)


# ── Конструктор агентов: модели, инструменты, агенты ───────────────────────────

@router.get("/models")
async def api_admin_models(admin: dict = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    return [_mc_dict(m) for m in await repo.list_model_configs(db)]


@router.post("/models")
async def api_admin_create_model(req: ModelConfigReq, admin: dict = Depends(admin_user),
                                 db: AsyncSession = Depends(get_db)):
    if await repo.get_model_config_by_alias(db, req.alias):
        raise HTTPException(400, "Модель с таким алиасом уже есть")
    mc = await repo.create_model_config(db, req.alias, req.provider,
                                        req.endpoint or "", req.fallback_to)
    await db.commit()
    return _mc_dict(mc)


@router.delete("/models/{mc_id}")
async def api_admin_delete_model(mc_id: int, admin: dict = Depends(admin_user),
                                 db: AsyncSession = Depends(get_db)):
    await repo.delete_model_config(db, mc_id)
    await repo.log_activity(db, admin["user_id"], "delete_model", f"Удалена модель (id {mc_id})")
    await db.commit()
    return {"ok": True}


@router.get("/tools")
async def api_admin_tools(admin: dict = Depends(admin_user)):
    """Инструменты для конструктора агентов — единый источник (issue #18)."""
    return tool_options()


@router.get("/agents")
async def api_admin_agents(admin: dict = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    return [_agent_dict(a) for a in await repo.list_agents(db)]


@router.post("/agents")
async def api_admin_create_agent(req: AgentReq, admin: dict = Depends(admin_user),
                                 db: AsyncSession = Depends(get_db)):
    agent = await repo.create_agent(db, req.name, req.system_prompt or "",
                                    req.tools, req.default_model, req.allowed_roles or "")
    await db.commit()
    return _agent_dict(agent)


@router.delete("/agents/{agent_id}")
async def api_admin_delete_agent(agent_id: int, admin: dict = Depends(admin_user),
                                 db: AsyncSession = Depends(get_db)):
    await repo.delete_agent(db, agent_id)
    await repo.log_activity(db, admin["user_id"], "delete_agent", f"Удалён агент (id {agent_id})")
    await db.commit()
    return {"ok": True}


# ── Экспорт отчётов ────────────────────────────────────────────────────────────

@router.get("/export/xlsx")
async def api_admin_export_xlsx(admin: dict = Depends(admin_user),
                                db: AsyncSession = Depends(get_db)):
    data = reports.build_xlsx(await _report_data(db))
    await repo.log_activity(db, admin["user_id"], "export", "Экспорт отчёта (xlsx)")
    await db.commit()
    return Response(content=data, media_type=_XLSX_MIME,
                    headers={"Content-Disposition": 'attachment; filename="report.xlsx"'})


@router.get("/export/docx")
async def api_admin_export_docx(admin: dict = Depends(admin_user),
                                db: AsyncSession = Depends(get_db)):
    data = reports.build_docx(await _report_data(db))
    await repo.log_activity(db, admin["user_id"], "export", "Экспорт отчёта (docx)")
    await db.commit()
    return Response(content=data, media_type=_DOCX_MIME,
                    headers={"Content-Disposition": 'attachment; filename="report.docx"'})


@router.get("/users/{uid}/export/docx")
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


# ── Issue #37 — подписки на тендеры и ручной прогон опроса ─────────────────────

def _sub_dict(sub):
    return {"id": sub.id, "name": sub.name, "keywords": sub.keywords,
            "region": sub.region, "budget_min": sub.budget_min,
            "budget_max": sub.budget_max, "customer": sub.customer,
            "recipient_roles": sub.recipient_roles, "active": bool(sub.active)}


@router.get("/tenders/subscriptions")
async def api_list_subscriptions(admin: dict = Depends(admin_user),
                                 db: AsyncSession = Depends(get_db)):
    return [_sub_dict(s) for s in await repo.list_subscriptions(db, only_active=False)]


@router.post("/tenders/subscriptions")
async def api_create_subscription(req: TenderSubscriptionReq, admin: dict = Depends(admin_user),
                                  db: AsyncSession = Depends(get_db)):
    sub = await repo.create_subscription(
        db, req.name, req.keywords, req.region, req.budget_min, req.budget_max,
        req.customer, req.recipient_roles or "закупки")
    await repo.log_activity(db, admin["user_id"], "tender_subscription",
                            f"Создана подписка «{req.name}»")
    await db.commit()
    return _sub_dict(sub)


@router.delete("/tenders/subscriptions/{sub_id}")
async def api_delete_subscription(sub_id: int, admin: dict = Depends(admin_user),
                                  db: AsyncSession = Depends(get_db)):
    await repo.delete_subscription(db, sub_id, is_admin=True)
    await db.commit()
    return {"ok": True}


@router.post("/tenders/poll")
async def api_run_tender_poll(admin: dict = Depends(admin_user),
                              db: AsyncSession = Depends(get_db)):
    """Ручной прогон опроса подписок (для проверки/по требованию; в проде — Celery beat)."""
    from services import tender_notify
    n = await tender_notify.poll_once(db)
    return {"new_notifications": n}
