"""Генерация документов.
- create_docx: markdown-подобный текст → .docx (портировано из mybot _create_docx_sync)
- create_pdf:  markdown-подобный текст → .pdf (reportlab, кириллица через TTF из конфига)
"""
import io
import os
import re
import sys

from app.config import get_settings

# TTF с кириллицей для PDF: из конфига, иначе системный дефолт по ОС.
PDF_FONT_PATH = get_settings().pdf_font_path or (
    "C:/Windows/Fonts/arial.ttf" if sys.platform == "win32"
    else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
)


def create_docx(content: str, filename: str = "document") -> bytes:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor

    GRAPHITE = RGBColor(0x26, 0x28, 0x2F)

    doc = Document()
    doc.core_properties.title = filename

    section = doc.sections[0]
    section.page_width = Cm(21)
    section.page_height = Cm(29.7)
    section.left_margin = Cm(2.0)
    section.right_margin = Cm(1.5)
    section.top_margin = Cm(0.46)
    section.bottom_margin = Cm(1.0)

    normal = doc.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(12)
    normal.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = 1.15

    RE_SECTION = re.compile(r"^(\d{1,2})\.\s+[А-ЯЁA-Z]")
    RE_SUBSECTION = re.compile(r"^\d+\.\d+")
    RE_TITLE_CAPS = re.compile(r"^[А-ЯЁA-Z\s№«»\d\-–—.,]+$")
    RE_MD_TABLE_ROW = re.compile(r"^\|(.+)\|$")
    RE_MD_TABLE_SEP = re.compile(r"^\|[-| :]+\|$")

    def _set_font(run, bold=False, size_pt=12, color=None):
        run.font.name = "Times New Roman"
        run.font.size = Pt(size_pt)
        run.bold = bold
        if color:
            run.font.color.rgb = color

    def _add_run(para, text, bold=False, size_pt=12, color=None):
        run = para.add_run(text)
        _set_font(run, bold=bold, size_pt=size_pt, color=color)
        return run

    def _add_inline(para, text):
        parts = text.split("**")
        for i, part in enumerate(parts):
            if part:
                run = para.add_run(part)
                _set_font(run, bold=(i % 2 == 1))

    def _set_cell_border(cell):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        for side in ("top", "left", "bottom", "right"):
            tag = OxmlElement(f"w:{side}")
            tag.set(qn("w:val"), "single")
            tag.set(qn("w:sz"), "4")
            tag.set(qn("w:color"), "000000")
            tcPr.append(tag)

    def _set_cell_no_border(cell):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        tcBorders = OxmlElement("w:tcBorders")
        for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
            tag = OxmlElement(f"w:{side}")
            tag.set(qn("w:val"), "none")
            tcBorders.append(tag)
        tcPr.append(tcBorders)

    def _set_cell_shading(cell, fill="D9D9D9"):
        tc = cell._tc
        tcPr = tc.get_or_add_tcPr()
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:color"), "auto")
        shd.set(qn("w:fill"), fill)
        tcPr.append(shd)

    def _para_in_cell(cell, text, bold=False, align=WD_ALIGN_PARAGRAPH.LEFT, size_pt=12):
        p = cell.paragraphs[0] if cell.paragraphs else cell.add_paragraph()
        p.clear()
        p.alignment = align
        p.paragraph_format.space_after = Pt(0)
        _add_run(p, text, bold=bold, size_pt=size_pt)
        return p

    def _build_header(logo_path, req_lines):
        hdr = doc.sections[0].header
        hdr.is_linked_to_previous = False
        for p in hdr.paragraphs:
            p._element.getparent().remove(p._element)
        htbl = hdr.add_table(rows=1, cols=2, width=Cm(17.5))
        htbl.autofit = False
        left_cell, right_cell = htbl.rows[0].cells[0], htbl.rows[0].cells[1]
        left_cell.width = Cm(6.0)
        right_cell.width = Cm(11.5)
        for cell in (left_cell, right_cell):
            _set_cell_no_border(cell)
        lp = left_cell.paragraphs[0]
        lp.paragraph_format.space_after = Pt(0)
        if logo_path and os.path.exists(logo_path):
            lp.add_run().add_picture(logo_path, width=Cm(5.7))
        else:
            _set_font(lp.add_run("[ЛОГОТИП]"), size_pt=11)
        for idx, line in enumerate(req_lines):
            rp = right_cell.paragraphs[0] if idx == 0 else right_cell.add_paragraph()
            rp.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            rp.paragraph_format.space_after = Pt(0)
            _set_font(rp.add_run(line), size_pt=11)

    def _make_md_table(rows):
        ncols = max(len(r) for r in rows)
        tbl = doc.add_table(rows=len(rows), cols=ncols)
        tbl.style = "Table Grid"
        for i, row in enumerate(rows):
            is_header = i == 0
            for j, cell_text in enumerate(row):
                cell = tbl.rows[i].cells[j]
                _para_in_cell(
                    cell, cell_text.strip(), bold=is_header,
                    align=WD_ALIGN_PARAGRAPH.CENTER if is_header else WD_ALIGN_PARAGRAPH.LEFT,
                )
                if is_header:
                    _set_cell_shading(cell)
        return tbl

    def _make_2col_table(rows, widths=(50, 50), borders=False):
        tbl = doc.add_table(rows=len(rows), cols=2)
        for i, (left, right) in enumerate(rows):
            lc, rc = tbl.rows[i].cells[0], tbl.rows[i].cells[1]
            _para_in_cell(lc, left)
            _para_in_cell(rc, right)
            for cell in (lc, rc):
                (_set_cell_border if borders else _set_cell_no_border)(cell)
        total_cm = 16.0
        for row in tbl.rows:
            row.cells[0].width = Cm(total_cm * widths[0] / 100)
            row.cells[1].width = Cm(total_cm * widths[1] / 100)
        return tbl

    lines = content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()

        if line.upper().startswith("[HEADER"):
            m = re.search(r"logo=([^\]]*)", line, re.I)
            logo_path = m.group(1).strip() if m else ""
            req_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().upper().startswith("[/HEADER"):
                req_lines.append(lines[i].strip())
                i += 1
            _build_header(logo_path, req_lines)
            i += 1
            continue

        if line.upper() == "[PAGEBREAK]":
            doc.add_page_break()
            i += 1
            continue

        if line.upper().startswith("[2COL"):
            m = re.search(r"widths?=(\d+)[,/](\d+)", line, re.I)
            w = (int(m.group(1)), int(m.group(2))) if m else (50, 50)
            rows_2col = []
            i += 1
            while i < len(lines) and not lines[i].strip().upper().startswith("[/2COL"):
                parts = lines[i].split("||")
                rows_2col.append((parts[0].strip() if parts else "",
                                  parts[1].strip() if len(parts) > 1 else ""))
                i += 1
            _make_2col_table(rows_2col, widths=w)
            i += 1
            continue

        if RE_MD_TABLE_ROW.match(line):
            md_rows = []
            while i < len(lines):
                l = lines[i].strip()
                if RE_MD_TABLE_SEP.match(l):
                    i += 1
                    continue
                if not RE_MD_TABLE_ROW.match(l):
                    break
                md_rows.append([c.strip() for c in l.strip("|").split("|")])
                i += 1
            if md_rows:
                _make_md_table(md_rows)
            continue

        i += 1

        if not line or line in ("---", "—--", "***"):
            doc.add_paragraph("")
            continue

        if line.startswith("# "):
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_run(p, line[2:], bold=True, size_pt=14, color=GRAPHITE); continue
        if line.startswith("## "):
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_run(p, line[3:], bold=True, size_pt=13, color=GRAPHITE); continue
        if line.startswith("### "):
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_run(p, line[4:], bold=True, size_pt=12, color=GRAPHITE); continue

        if RE_SECTION.match(line) and not RE_SUBSECTION.match(line):
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_run(p, line, bold=True, size_pt=12, color=GRAPHITE); continue

        if RE_TITLE_CAPS.match(line) and 2 <= len(line) <= 80 and len(line.split()) <= 12:
            p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            _add_run(p, line, bold=True, size_pt=13, color=GRAPHITE); continue

        p = doc.add_paragraph()
        if RE_SUBSECTION.match(line) or line.startswith("—") or line.startswith("-"):
            p.paragraph_format.left_indent = Cm(0.63)
        else:
            p.paragraph_format.first_line_indent = Cm(0.63)
        _add_inline(p, line)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


_PDF_FONT_REGISTERED = False


def _register_pdf_font() -> str:
    """Регистрирует TTF с кириллицей в reportlab. Возвращает имя шрифта."""
    global _PDF_FONT_REGISTERED
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    if _PDF_FONT_REGISTERED:
        return "AppFont"
    if PDF_FONT_PATH and os.path.exists(PDF_FONT_PATH):
        pdfmetrics.registerFont(TTFont("AppFont", PDF_FONT_PATH))
        _PDF_FONT_REGISTERED = True
        return "AppFont"
    return "Helvetica"  # без кириллицы, но не падаем


def create_pdf(content: str, filename: str = "document") -> bytes:
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    font = _register_pdf_font()
    styles = getSampleStyleSheet()
    body = ParagraphStyle("Body", parent=styles["Normal"], fontName=font,
                          fontSize=11, leading=15, alignment=TA_JUSTIFY)
    h1 = ParagraphStyle("H1", parent=body, fontSize=15, leading=19,
                        alignment=TA_CENTER, spaceAfter=10)
    h2 = ParagraphStyle("H2", parent=body, fontSize=13, leading=17,
                        alignment=TA_CENTER, spaceAfter=8)

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=2 * cm, rightMargin=1.5 * cm,
                            topMargin=1.5 * cm, bottomMargin=1.5 * cm, title=filename)
    flow = []

    def esc(s: str) -> str:
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # **bold** → <b>
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        return s

    for raw in content.split("\n"):
        line = raw.strip()
        if not line:
            flow.append(Spacer(1, 6))
        elif line.startswith("# "):
            flow.append(Paragraph(esc(line[2:]), h1))
        elif line.startswith("## "):
            flow.append(Paragraph(esc(line[3:]), h2))
        elif line.startswith("### "):
            flow.append(Paragraph(esc(line[4:]), h2))
        else:
            flow.append(Paragraph(esc(line), body))

    pdf.build(flow)
    return buf.getvalue()
