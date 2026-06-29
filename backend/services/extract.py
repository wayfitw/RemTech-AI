"""Извлечение текста из загруженных файлов для передачи в контекст Claude."""
import io


def detect_kind(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "docx":
        return "docx"
    if ext == "pptx":
        return "pptx"
    if ext == "xlsx":
        return "xlsx"
    if ext == "pdf":
        return "pdf"
    if ext in ("jpg", "jpeg", "png", "gif", "webp"):
        return "image"
    if ext in ("txt", "md", "csv"):
        return "text"
    return "other"


def extract_text(data: bytes, filename: str) -> str:
    kind = detect_kind(filename)
    try:
        if kind == "docx":
            return _docx_text(data)
        if kind == "pdf":
            return _pdf_text(data)
        if kind == "xlsx":
            return _xlsx_text(data)
        if kind == "pptx":
            return _pptx_text(data)
        if kind == "text":
            return data.decode("utf-8", errors="replace")[:20000]
    except Exception as e:
        return f"[Не удалось извлечь текст из {filename}: {e}]"
    return ""


def _docx_text(data: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(data))
    parts = [p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                parts.append(" | ".join(cells))
    return "\n".join(parts)[:20000]


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    parts = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(parts)[:20000]


def _xlsx_text(data: bytes) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    parts = []
    for ws in wb.worksheets:
        parts.append(f"# Лист: {ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = [str(c) for c in row if c is not None]
            if cells:
                parts.append(" | ".join(cells))
    return "\n".join(parts)[:20000]


def _pptx_text(data: bytes) -> str:
    from pptx import Presentation
    prs = Presentation(io.BytesIO(data))
    parts = []
    for idx, slide in enumerate(prs.slides, 1):
        parts.append(f"# Слайд {idx}")
        for shape in slide.shapes:
            if shape.has_text_frame and shape.text_frame.text.strip():
                parts.append(shape.text_frame.text)
    return "\n".join(parts)[:20000]
