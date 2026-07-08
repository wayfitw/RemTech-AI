"""TASK-0306 — правила классификации документов при загрузке базы знаний."""
from scripts.ingest_kb import build_plan, classify


def _row(sens="Внутренний", layer="да", fmt="docx", file="f.docx", typ="DI"):
    return {"Чувствительность": sens, "Текстовый слой": layer, "Формат": fmt,
            "Файл": file, "Тип": typ}


def test_commercial_secret_skipped():
    action, role, _ = classify(_row(sens="Коммерческая тайна"))
    assert action == "skip"


def test_pii_restricted_to_admin():
    action, role, _ = classify(_row(sens="Содержит ПДн (реквизиты контрагентов)"))
    assert action == "load" and role == "admin"


def test_unsupported_formats_skipped():
    for fmt in ("doc", "xls", "jpg"):
        action, _, _ = classify(_row(fmt=fmt))
        assert action == "skip", fmt


def test_scan_without_text_skipped():
    action, _, _ = classify(_row(layer="НЕТ (скан; см. одноимённый .txt)"))
    assert action == "skip"


def test_internal_loads_for_all():
    action, role, _ = classify(_row(sens="Внутренний"))
    assert action == "load" and role is None


def test_build_plan_counts():
    rows = [_row(sens="Коммерческая тайна"), _row(), _row(sens="Содержит ПДн")]
    load, skip = build_plan(rows)
    assert len(load) == 2 and len(skip) == 1
