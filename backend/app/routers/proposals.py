"""TASK-0507 (#45) — REST для КП-презентаций на технику (PPTX).

Поток мастера: загрузка документа поставщика → извлечение структуры (через шлюз) →
правка блоков + загрузка фото → генерация PPTX → скачивание. Всё под auth + RBAC
(продажи/руководство/admin — единый источник ролей: registry.role_can_use_tool).

БЕЗОПАСНОСТЬ фото (критерий #45): image_ref — это ID файла в хранилище, а НЕ путь.
При генерации фото берётся только если файл принадлежит текущему пользователю
(владелец) или он admin. Чтения произвольных путей из прототипа нет в принципе.
Скачивание готового PPTX — через существующий GET /api/files/{id} (та же owner-проверка).
"""
import asyncio

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from agent.registry import role_can_use_tool
from app import repositories as repo
from app import storage
from app.config import get_settings
from app.database import get_db
from app.deps import _read_upload_limited, current_user
from services import docgen, filecheck, proposal_pptx
from services.extract import detect_kind

router = APIRouter(prefix="/api/proposals")

_TOOL = "create_proposal_pptx"   # единый ключ RBAC (продажи/руководство)
# Лимит Bot API на отправку документа ботом — 50 МБ (#55). Больше — отдаём ссылку.
TELEGRAM_FILE_LIMIT = 50 * 1024 * 1024


def sales_user(user: dict = Depends(current_user)) -> dict:
    """Доступ к КП-презентациям — тем же ролям, что и инструмент create_proposal_pptx."""
    if not role_can_use_tool(user.get("role", ""), _TOOL):
        raise HTTPException(403, "Доступ только для ролей «продажи» / «руководство»")
    return user


async def _resolve_owned_image(db, image_id, user: dict) -> bytes | None:
    """Фото по ID из хранилища — ТОЛЬКО своё (владелец) или для admin. Иначе 403.
    Не изображение / нет файла → None (слайд соберётся с плейсхолдером)."""
    try:
        rec = await repo.get_file_record(db, int(image_id))
    except (TypeError, ValueError):
        return None
    if not rec or rec.kind != "image":
        return None
    if rec.user_id != user["user_id"] and user.get("role") != "admin":
        raise HTTPException(403, "Нет доступа к изображению")
    res = storage.read_record_bytes(rec)
    return res[0] if res else None


@router.post("/extract")
async def api_extract(file: UploadFile = File(...), user: dict = Depends(sales_user),
                      db: AsyncSession = Depends(get_db)):
    """Документ поставщика (PDF/DOCX/…) → структура КП (для правки в мастере)."""
    data = await _read_upload_limited(file)
    if err := filecheck.ensure_allowed(file.filename, data):
        raise HTTPException(400, err)
    try:
        return await proposal_pptx.extract_slides_from_document(data, file.filename, db)
    except proposal_pptx.ExtractionError as e:
        raise HTTPException(422, str(e))


@router.post("/photo")
async def api_photo(file: UploadFile = File(...), user: dict = Depends(sales_user),
                    db: AsyncSession = Depends(get_db)):
    """Загрузка фото техники → image_id (для ссылки из блока split/photo)."""
    data = await _read_upload_limited(file)
    if err := filecheck.ensure_allowed(file.filename, data):
        raise HTTPException(400, err)
    if detect_kind(file.filename) != "image":
        raise HTTPException(400, "Ожидается изображение (jpg/png/webp)")
    rec = await storage.save_bytes(db, user["user_id"], None, file.filename, data,
                                   kind="image", direction="upload")
    await db.commit()
    return {"image_id": rec.id, "name": file.filename}


@router.post("/generate")
async def api_generate(payload: dict = Body(...), user: dict = Depends(sales_user),
                       db: AsyncSession = Depends(get_db)):
    """Структура КП (+ image_id в блоках) → PPTX. Возвращает file_id для скачивания
    через GET /api/files/{id}."""
    blocks = []
    for b in payload.get("blocks") or []:
        b = dict(b)
        img_id = b.pop("image_id", None)
        b.pop("_image", None)   # клиент не может подсунуть байты напрямую
        if img_id is not None and (b.get("type") or "").lower() in ("split", "photo"):
            blob = await _resolve_owned_image(db, img_id, user)
            if blob:
                b["_image"] = blob
        blocks.append(b)
    spec = {**payload, "blocks": blocks}
    spec.pop("filename", None)
    try:
        data = await asyncio.to_thread(docgen.create_proposal_pptx, spec)
    except ValueError as e:                # #53 — неизвестный шаблон
        raise HTTPException(400, str(e))
    fname = (payload.get("filename") or payload.get("name") or "КП") + ".pptx"
    rec = await storage.save_bytes(db, user["user_id"], None, fname, data,
                                   kind="pptx", direction="output")
    # #54 — запись в историю (снимок контракта без байтов картинок) + ретенция 30
    snapshot = {k: v for k, v in payload.items() if k != "blocks"}
    snapshot["blocks"] = [{k: v for k, v in b.items() if k != "_image"}
                          for b in (payload.get("blocks") or [])]
    await repo.add_proposal_history(
        db, user_id=user["user_id"], file_id=rec.id, file_name=fname,
        client_name=payload.get("client_name") or "", machine=payload.get("name") or "",
        template=(payload.get("template") or "standard"), payload=snapshot)
    await db.commit()
    return {"file_id": rec.id, "name": fname}


@router.get("/history")
async def api_history(user: dict = Depends(sales_user), db: AsyncSession = Depends(get_db)):
    """#54 — последние 30 КП пользователя (только свои). Для повторного скачивания
    (file_id → GET /api/files/{id}) и как основа нового КП (payload)."""
    rows = await repo.list_proposal_history(db, user["user_id"])
    return [{"id": r.id, "file_id": r.file_id, "name": r.file_name,
             "client_name": r.client_name, "machine": r.machine, "template": r.template,
             "created_at": repo.iso(r.created_at)} for r in rows]


@router.get("/history/{item_id}")
async def api_history_item(item_id: int, user: dict = Depends(sales_user),
                           db: AsyncSession = Depends(get_db)):
    """Снимок контракта данных прошлого КП — чтобы пересобрать или взять за основу."""
    row = await repo.get_proposal_history(db, item_id)
    if not row:
        raise HTTPException(404, "Запись не найдена")
    if row.user_id != user["user_id"] and user.get("role") != "admin":
        raise HTTPException(403, "Нет доступа к этому КП")
    return {"id": row.id, "file_id": row.file_id, "name": row.file_name,
            "template": row.template, "payload": row.payload or {}}


@router.post("/send-telegram")
async def api_send_telegram(payload: dict = Body(...), user: dict = Depends(sales_user),
                            db: AsyncSession = Depends(get_db)):
    """#55 — отправка готового PPTX в Telegram через платформенный бот.

    Получатель — Telegram-аккаунт, связанный с учётной записью (allow-list бота);
    можно указать chat_id явно, но только из allow-list (чужие чаты недоступны).
    Файл берётся ТОЛЬКО свой (или admin). Файл больше лимита Telegram (50 МБ для
    ботов) — отдаём ссылку на скачивание вместо файла.
    """
    settings = get_settings()
    file_id = payload.get("file_id")
    rec = await repo.get_file_record(db, int(file_id)) if file_id else None
    if not rec:
        raise HTTPException(404, "Файл не найден")
    if rec.user_id != user["user_id"] and user.get("role") != "admin":
        raise HTTPException(403, "Нет доступа к файлу")
    if not settings.telegram_bot_token:
        raise HTTPException(503, "Telegram-бот не настроен")

    allowmap = settings.telegram_allowmap                      # tg_id → username
    requested = payload.get("chat_id")
    if requested is not None:
        try:
            chat_id = int(requested)
        except (TypeError, ValueError):
            raise HTTPException(400, "Некорректный chat_id")
        if chat_id not in allowmap:
            raise HTTPException(403, "Получатель не в списке разрешённых бота")
    else:
        chat_id = next((tid for tid, uname in allowmap.items()
                        if uname == user["username"]), None)
        if chat_id is None:
            raise HTTPException(400, "Ваш Telegram не привязан — укажите chat_id "
                                     "из списка разрешённых или обратитесь к администратору")

    blob = storage.read_record_bytes(rec)
    if not blob:
        raise HTTPException(404, "Файл недоступен в хранилище")
    data, name = blob
    if len(data) > TELEGRAM_FILE_LIMIT:
        return {"sent": False, "reason": "too_large",
                "download_url": f"/api/files/{rec.id}",
                "detail": (f"Файл {len(data) // (1024 * 1024)} МБ — больше лимита Telegram "
                           f"({TELEGRAM_FILE_LIMIT // (1024 * 1024)} МБ). Скачайте по ссылке.")}

    from app.telegram_bot import TelegramTransport
    tx = TelegramTransport(settings.telegram_bot_token)
    try:
        await tx.send_file(chat_id, data, name, "sendDocument", "document")
    except Exception as e:                                     # noqa: BLE001 — сеть/Bot API
        raise HTTPException(502, f"Не удалось отправить в Telegram: {e}")
    finally:
        await tx.aclose()
    return {"sent": True, "chat_id": chat_id, "name": name}
