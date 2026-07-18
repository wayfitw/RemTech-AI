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
from app.database import get_db
from app.deps import _read_upload_limited, current_user
from services import docgen, filecheck, proposal_pptx
from services.extract import detect_kind

router = APIRouter(prefix="/api/proposals")

_TOOL = "create_proposal_pptx"   # единый ключ RBAC (продажи/руководство)


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
    data = await asyncio.to_thread(docgen.create_proposal_pptx, spec)
    fname = (payload.get("filename") or payload.get("name") or "КП") + ".pptx"
    rec = await storage.save_bytes(db, user["user_id"], None, fname, data,
                                   kind="pptx", direction="output")
    await db.commit()
    return {"file_id": rec.id, "name": fname}
