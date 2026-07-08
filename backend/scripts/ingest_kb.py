"""TASK-0306 — загрузка первой партии документов базы знаний.

Читает REESTR_документов.csv и по правилам из аудита БЗ решает, что грузить в RAG,
с каким owner_role, а что пропустить (коммерческая тайна, сканы без текста,
неподдерживаемые форматы). owner_role проставляется по колонке «Чувствительность».

Использование:
    python -m scripts.ingest_kb --source "C:/path/База знаний" --dry-run   # только план
    python -m scripts.ingest_kb --source "C:/path/База знаний"             # загрузка

Скрипт запускать из каталога backend (нужен пакет app).
"""
import argparse
import asyncio
import csv
import sys
from pathlib import Path

REESTR = "REESTR_документов.csv"
# форматы, которые конвейер не парсит (whitelist: pdf/docx/xlsx/pptx/txt/md/csv)
_UNSUPPORTED = {"doc", "xls", "jpg", "jpeg", "png"}


def classify(row: dict) -> tuple[str, str | None, str]:
    """→ (action 'load'|'skip', owner_role|None, причина)."""
    sens = (row.get("Чувствительность") or "").strip()
    layer = (row.get("Текстовый слой") or "").strip()
    fmt = (row.get("Формат") or "").strip().lower()

    if "Коммерческая тайна" in sens:
        return "skip", None, "коммерческая тайна — до маршрутизации по чувствительности (TASK-0207)"
    if fmt in _UNSUPPORTED:
        return "skip", None, f"формат .{fmt} не поддерживается (пересохранить/OCR)"
    if layer.upper().startswith("НЕТ"):
        return "skip", None, "нет текстового слоя (скан/фото — грузится .txt/.xlsx-замена)"
    if "ПДн" in sens:
        return "load", "admin", "содержит ПДн → доступ только admin (152-ФЗ)"
    return "load", None, "ок — доступно сотрудникам"


def read_registry(root: Path) -> list[dict]:
    csv_path = root / REESTR
    if not csv_path.exists():
        sys.exit(f"Не найден реестр: {csv_path}")
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))


def build_plan(rows: list[dict]) -> tuple[list, list]:
    load, skip = [], []
    for r in rows:
        action, role, reason = classify(r)
        entry = {"file": r.get("Файл", ""), "role": role, "reason": reason,
                 "type": r.get("Тип", ""), "sens": r.get("Чувствительность", "")}
        (load if action == "load" else skip).append(entry)
    return load, skip


def print_plan(load: list, skip: list) -> None:
    print(f"\n=== ПЛАН ЗАГРУЗКИ: грузим {len(load)}, пропускаем {len(skip)} ===\n")
    print(f"--- ГРУЗИМ ({len(load)}) ---")
    for e in load:
        role = e["role"] or "все"
        print(f"  [{role:>5}] {e['file']}")
    print(f"\n--- ПРОПУСКАЕМ ({len(skip)}) ---")
    for e in skip:
        print(f"  ✗ {e['file']}  — {e['reason']}")


async def ingest(root: Path, load: list) -> None:
    from app import kb
    from app.config import get_settings
    from app.database import SessionLocal
    from app.embeddings import get_embedder
    from services.extract import extract_text

    settings = get_settings()
    embedder = get_embedder()
    ok, failed = 0, 0
    async with SessionLocal() as s:
        for e in load:
            path = root / e["file"]
            if not path.exists():
                print(f"  ! файл не найден: {path}")
                failed += 1
                continue
            data = path.read_bytes()
            text = extract_text(data, path.name, max_chars=settings.kb_extract_max_chars)
            # реестр может помечать скан-образ как «текстовый слой: да», а по факту
            # извлекается 15-20 символов — такой документ-призрак не индексируем
            if len(text.strip()) < 100:
                print(f"  ! мало текста ({len(text.strip())} симв., похоже скан/образ): {e['file']}")
                failed += 1
                continue
            res = await kb.ingest_document(s, embedder, path.name, text,
                                           owner_role=e["role"], source="kb:" + e["type"])
            await s.commit()
            print(f"  ✓ {e['file']} — {res['chunks']} чанков (role={e['role'] or 'все'})")
            ok += 1
    print(f"\n=== ГОТОВО: загружено {ok}, ошибок {failed} ===")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="каталог «База знаний» (с REESTR)")
    ap.add_argument("--dry-run", action="store_true", help="только показать план")
    args = ap.parse_args()

    root = Path(args.source)
    load, skip = build_plan(read_registry(root))
    print_plan(load, skip)
    if args.dry_run:
        print("\n(dry-run — ничего не загружено)")
        return
    asyncio.run(ingest(root, load))


if __name__ == "__main__":
    main()
