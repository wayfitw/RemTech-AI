"""Тесты генерации документов (docgen), редактора docx (doc_editor), извлечения (extract)."""
import io
import re

from services import docgen
from services.extract import detect_kind, extract_text
from utils.doc_editor import apply_doc_edits, read_doc

SAMPLE = "# Договор\n**Жирный** абзац про XCMG.\n\n| A | B |\n|---|---|\n| 1 | 2 |"


def test_create_docx_is_valid():
    from docx import Document
    data = docgen.create_docx(SAMPLE, "test")
    assert len(data) > 1000
    doc = Document(io.BytesIO(data))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Договор" in text and "XCMG" in text


def test_create_pdf_is_valid():
    data = docgen.create_pdf("# Заголовок\nКириллический текст.", "test")
    assert data[:5] == b"%PDF-" and len(data) > 800


def test_doc_editor_read_and_edit_roundtrip():
    dx = docgen.create_docx("Первый абзац.\n\nВторой абзац.", "d")
    listing = read_doc(dx)
    assert "P1#" in listing or "параграф" in listing.lower()
    ref = re.search(r"P\d+#\w+", listing).group(0)
    out, diff = apply_doc_edits(dx, [{"op": "rewrite", "ref": ref, "new_text": "Изменённый абзац."}])
    assert len(out) > 1000
    from docx import Document
    text = "\n".join(p.text for p in Document(io.BytesIO(out)).paragraphs)
    assert "Изменённый абзац." in text


def test_create_proposal():
    from docx import Document
    data = {
        "filename": "kp", "title": "Поставка спецтехники", "client": "ООО «Стройка»",
        "markup_percent": 12, "validity_days": 14, "contact": "Иван · +7 900 000",
        "items": [
            {"name": "Экскаватор XCMG XE215C", "qty": 1, "price": 9850000},
            {"name": "Ковш дополнительный", "qty": 2, "price": 150000},
        ],
    }
    out = docgen.create_proposal(data)
    assert len(out) > 1000
    text = "\n".join(p.text for p in Document(io.BytesIO(out)).paragraphs)
    tables_text = " ".join(
        c.text for t in Document(io.BytesIO(out)).tables for row in t.rows for c in row.cells)
    assert "КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ" in tables_text
    assert "Стройка" in text
    assert "Экскаватор XCMG XE215C" in tables_text
    # экскаватор с наценкой 12%: 9 850 000 * 1.12 = 11 032 000
    assert "11 032 000" in tables_text
    # итог: 11 032 000 + 2*150 000*1.12 = 11 368 000
    assert "11 368 000" in tables_text


def test_detect_kind():
    assert detect_kind("a.docx") == "docx"
    assert detect_kind("b.PDF") == "pdf"
    assert detect_kind("c.png") == "image"
    assert detect_kind("d.xlsx") == "xlsx"
    assert detect_kind("e.unknown") == "other"


def test_extract_text_from_docx():
    dx = docgen.create_docx("Прайс на запчасти XCMG.", "p")
    text = extract_text(dx, "p.docx")
    assert "запчасти" in text
