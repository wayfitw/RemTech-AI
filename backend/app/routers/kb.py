"""Роутер базы знаний (только admin): загрузка, список, удаление документов."""
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app import kb
from app import repositories as repo
from app.config import get_settings
from app.database import get_db
from app.deps import _read_upload_limited, admin_user, embedder_dep
from services import filecheck
from services.extract import extract_text

router = APIRouter(prefix="/api/admin/kb")
settings = get_settings()


@router.post("/upload")
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


@router.get("")
async def api_admin_kb_list(admin: dict = Depends(admin_user), db: AsyncSession = Depends(get_db)):
    return await repo.list_kb_documents(db)


@router.delete("/{document_id}")
async def api_admin_kb_delete(document_id: int, admin: dict = Depends(admin_user),
                              db: AsyncSession = Depends(get_db)):
    await repo.delete_kb_document(db, document_id)
    await repo.log_activity(db, admin["user_id"], "kb_delete", f"Удалён документ БЗ (id {document_id})")
    await db.commit()
    return {"ok": True}
