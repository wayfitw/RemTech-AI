"""Хранение файлов на диске + запись в БД. Возвращает file_id для скачивания."""
import uuid
from pathlib import Path

import db
from config import FILES_DIR


def save_bytes(
    user_id: int,
    conversation_id: int | None,
    file_name: str,
    data: bytes,
    kind: str = "other",
    direction: str = "output",
) -> int:
    """Сохраняет байты в FILES_DIR под уникальным именем, пишет запись в БД.
    Возвращает file_id."""
    ext = file_name.rsplit(".", 1)[-1] if "." in file_name else "bin"
    disk_name = f"{uuid.uuid4().hex}.{ext}"
    path = Path(FILES_DIR) / disk_name
    path.write_bytes(data)
    return db.save_file_record(
        user_id=user_id,
        file_name=file_name,
        file_path=str(path),
        kind=kind,
        conversation_id=conversation_id,
        direction=direction,
    )


def read_bytes(file_id: int) -> tuple[bytes, str] | None:
    rec = db.get_file_record(file_id)
    if not rec:
        return None
    path = Path(rec["file_path"])
    if not path.exists():
        return None
    return path.read_bytes(), rec["file_name"]
