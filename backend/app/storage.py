"""Cutover Стадия 3 — хранение файлов на диске + запись в БД (async)."""
import uuid
from pathlib import Path

from app import repositories as repo
from app.config import get_settings

FILES_DIR = Path(get_settings().files_dir)
FILES_DIR.mkdir(parents=True, exist_ok=True)


async def save_bytes(session, user_id: int, conversation_id: int | None,
                     file_name: str, data: bytes, kind: str = "other",
                     direction: str = "output"):
    """Сохраняет байты под уникальным именем и создаёт запись uploaded_files."""
    ext = file_name.rsplit(".", 1)[-1] if "." in file_name else "bin"
    path = FILES_DIR / f"{uuid.uuid4().hex}.{ext}"
    path.write_bytes(data)
    return await repo.save_file_record(
        session, user_id, file_name, str(path), kind=kind,
        conversation_id=conversation_id, direction=direction,
    )


def read_record_bytes(rec) -> tuple[bytes, str] | None:
    """Читает байты по записи uploaded_files."""
    path = Path(rec.file_path)
    if not path.exists():
        return None
    return path.read_bytes(), rec.file_name
