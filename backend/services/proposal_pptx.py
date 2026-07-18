"""TASK-0507 (#45) — КП-презентация на технику (.pptx) в фирменном стиле «Ремтехники».

Симметрично docgen.create_proposal (Word/PDF): здесь — PPTX 16:9. Перенос раскладки
из прототипа kp-generator/server/generator.js; бренд и реквизиты — из docx_style.py.
Экспортируется как docgen.create_proposal_pptx (см. импорт в docgen.py).

БЕЗОПАСНОСТЬ: модуль сети/ФС НЕ трогает — картинки приходят БАЙТАМИ в blocks[i]
["_image"]. Резолв image_ref по белому списку и проверку доступа владельца делает
слой эндпоинта (критерий безопасности #45), а не генератор. Нет байтов → серый
плейсхолдер «Фото техники».
"""
from __future__ import annotations

import io

from services.docx_style import COMPANY, DARK, HAIRLINE, INK, SOFT, YELLOW

DEFAULT_TRUSTED = (
    "АО «СУЭК», АК «АЛРОСА», ПАО «Русал», АО «Полюс», ГМК «Норильский никель», "
    "АО «Евраз», ПАО «НЛМК», АО «Металлоинвест», АО «Северсталь», АО «ММК»")


def create_proposal_pptx(data: dict) -> bytes:
    """КП-презентация на технику (.pptx). Возвращает байты файла.

    data = {
        "name": "Экскаватор XCMG XE215C",     # модель — строка машины на слайдах
        "brand": "XCMG",                        # бренд — справа в шапке
        "manager": "Иван Петров", "phone": "+7 …",
        "client_name": "ООО «Стройка»",         # «Подготовлено для» на обложке
        "trusted_by": "…",                       # строка «Нам доверяют» (или дефолт)
        "warranty": "12 мес.", "availability": "склад, 14 дней",
        "price": "9 850 000 ₽", "payment_terms": ["50% аванс", "50% по факту"],
        "blocks": [
            {"type": "title", "title": "…", "text": "краткие характеристики"},
            {"type": "split", "rows": [["Мощность", "150 кВт"], ["ДВИГАТЕЛЬ", None], …],
             "_image": b"..."},                  # None во 2-м столбце → тёмный подзаголовок
            {"type": "table", "title": "…", "rows": [["a", "b"], …]},
            {"type": "photo", "title": "…", "_image": b"..."},
            {"type": "text",  "title": "…", "text": "…"},
        ],
    }
    Слайд «Цена и условия» добавляется автоматически последним.
    """
    from pptx import Presentation
    from pptx.dml.color import RGBColor
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
    from pptx.util import Emu, Inches, Pt

    # Палитра: бренд — из docx_style; служебные нейтральные тона — локально.
    C_YELLOW = RGBColor.from_string(YELLOW)
    C_DARK = RGBColor.from_string(DARK)
    C_INK = RGBColor.from_string(INK)
    C_WHITE = RGBColor.from_string("FFFFFF")
    C_MUTED = RGBColor.from_string("777777")
    C_SOFT = RGBColor.from_string(SOFT)
    C_BORDER = RGBColor.from_string(HAIRLINE)
    C_PHOTO_BG = RGBColor.from_string("DCDCDC")
    C_PHOTO_TX = RGBColor.from_string("999999")
    C_EVEN = RGBColor.from_string("F2F2F2")
    C_ODD = RGBColor.from_string("FAFAFA")
    C_TRUST_BG = RGBColor.from_string("EEEEEE")
    C_TRUST_TX = RGBColor.from_string("666666")
    C_SPEC = RGBColor.from_string("AAAAAA")
    FONT = "Arial"

    W, H = 10.0, 5.625                    # дюймы, 16:9
    HDR_H, NM_H = 0.80, 0.40
    CON_Y = HDR_H + NM_H + 0.04
    CON_H = H - CON_Y - 0.08

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(W), Inches(H)
    blank = prs.slide_layouts[6]

    def _slide():
        s = prs.slides.add_slide(blank)
        s.background.fill.solid()
        s.background.fill.fore_color.rgb = C_WHITE
        return s

    def _rect(slide, x, y, w, h, color, line=None, line_pt=0.0):
        sp = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        sp.fill.solid()
        sp.fill.fore_color.rgb = color
        if line is not None:
            sp.line.color.rgb = line
            sp.line.width = Pt(line_pt or 1)
        else:
            sp.line.fill.background()
        sp.shadow.inherit = False
        return sp

    def _text(slide, x, y, w, h, text, size, color, *, bold=False, align=PP_ALIGN.LEFT,
              anchor=MSO_ANCHOR.MIDDLE, spacing=None, wrap=True):
        tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = tb.text_frame
        tf.word_wrap = wrap
        tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = Emu(9144)
        tf.margin_top = tf.margin_bottom = 0
        first = True
        for line in str(text).split("\n"):
            p = tf.paragraphs[0] if first else tf.add_paragraph()
            first = False
            p.alignment = align
            r = p.add_run()
            r.text = line
            r.font.size, r.font.bold, r.font.name = Pt(size), bold, FONT
            r.font.color.rgb = color
            if spacing is not None:
                r.font._rPr.set("spc", str(int(spacing * 100)))
        return tb

    def _placeholder(slide, x, y, w, h):
        _rect(slide, x, y, w, h, C_PHOTO_BG)
        _text(slide, x, y, w, h, "📷 Фото техники", 14, C_PHOTO_TX,
              align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)

    def _image_contain(slide, blob, x, y, w, h):
        """Фото техники вписываем БЕЗ обрезки (contain, по центру) — модель не режем."""
        try:
            from PIL import Image
            iw, ih = Image.open(io.BytesIO(blob)).size
            box_ar, img_ar = w / h, iw / ih
            if img_ar > box_ar:
                dw, dh = w, w / img_ar
            else:
                dh, dw = h, h * img_ar
            px, py = x + (w - dw) / 2, y + (h - dh) / 2
            slide.shapes.add_picture(io.BytesIO(blob), Inches(px), Inches(py), Inches(dw), Inches(dh))
            return True
        except Exception:
            _placeholder(slide, x, y, w, h)
            return False

    def _header(slide, brand):
        _rect(slide, 0, 0, W, HDR_H, C_WHITE)
        _rect(slide, 0.14, 0.13, 0.54, 0.54, C_YELLOW)
        _text(slide, 0.14, 0.13, 0.54, 0.54, "RT", 17, C_INK, bold=True,
              align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        _text(slide, 0.80, 0.10, 5.2, 0.24, COMPANY["name"], 10, C_INK, bold=True)
        _text(slide, 0.80, 0.34, 5.2, 0.20,
              f"ИНН {COMPANY['inn']}  КПП {COMPANY['kpp']}", 8, C_MUTED)
        _text(slide, 0.80, 0.54, 5.2, 0.20, f"ОГРН {COMPANY['ogrn']}", 8, C_MUTED)
        if brand:
            _text(slide, 6.3, 0.13, 3.55, 0.54, brand, 15, C_INK, bold=True, align=PP_ALIGN.RIGHT)
        _rect(slide, 0, HDR_H - 0.03, W, 0.03, C_YELLOW)

    def _machine_name(slide, name):
        if name:
            _text(slide, 0.2, HDR_H + 0.03, 9.6, NM_H - 0.03, name, 12, C_INK, bold=True)

    def _title(block, brand, client):
        s = _slide()
        _rect(s, 0, 0, W, H, C_WHITE)
        _rect(s, 0, 0, W, H * 0.56, C_DARK)
        _rect(s, 0, H * 0.56, W, 0.06, C_YELLOW)
        _rect(s, 0.3, 0.22, 0.50, 0.50, C_YELLOW)
        _text(s, 0.3, 0.22, 0.50, 0.50, "RT", 16, C_INK, bold=True,
              align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
        _text(s, 0.90, 0.22, 5, 0.50, "РЕМТЕХНИКА", 20, C_YELLOW, bold=True)
        if brand:
            _text(s, 6, 0.22, 3.8, 0.50, brand, 15, C_WHITE, align=PP_ALIGN.RIGHT)
        _text(s, 0.3, 1.05, 9.4, 0.36, "КОММЕРЧЕСКОЕ ПРЕДЛОЖЕНИЕ", 11, C_YELLOW, spacing=2)
        _text(s, 0.3, 1.45, 9.4, 1.35, block.get("title") or "", 28, C_WHITE, bold=True)
        if block.get("text"):
            _text(s, 0.3, 2.82, 9.4, 0.40, block["text"], 11, C_SPEC)
        if client:
            _text(s, 0.3, H * 0.60, 3.5, 0.28, "Подготовлено для:", 9, C_MUTED)
            _text(s, 0.3, H * 0.60 + 0.27, 6, 0.38, client, 15, C_INK, bold=True)
        _rect(s, 0, H - 0.18, W, 0.18, C_YELLOW)

    def _split(block, brand, name):
        s = _slide()
        _header(s, brand)
        _machine_name(s, name)
        PHOTO_W = 5.20
        TABLE_X = PHOTO_W + 0.30
        TABLE_W = W - TABLE_X - 0.12
        _rect(s, PHOTO_W + 0.14, CON_Y, 0.015, CON_H, C_BORDER)
        blob = block.get("_image")
        if blob:
            _image_contain(s, blob, 0.14, CON_Y, PHOTO_W, CON_H)
        else:
            _placeholder(s, 0.14, CON_Y, PHOTO_W, CON_H)

        rows = [r for r in (block.get("rows") or []) if r and (r[0] or (len(r) > 1 and r[1]))]
        if not rows:
            return
        sections = sum(1 for r in rows if len(r) > 1 and r[1] is None)
        data_n = len(rows) - sections
        SEC_H = 0.27
        DATA_H = min(0.265, (CON_H - sections * SEC_H) / max(data_n, 1))
        cur_y, data_i = CON_Y, 0
        for row in rows:
            if cur_y + 0.1 > CON_Y + CON_H:
                break
            is_section = len(row) > 1 and row[1] is None
            if is_section:
                _rect(s, TABLE_X, cur_y, TABLE_W, SEC_H, C_DARK)
                _text(s, TABLE_X + 0.08, cur_y, TABLE_W - 0.08, SEC_H,
                      (row[0] or "").upper(), 8, C_YELLOW, bold=True)
                cur_y += SEC_H
            else:
                val = row[1] if len(row) > 1 else ""
                bg = C_EVEN if data_i % 2 == 0 else C_ODD
                data_i += 1
                _rect(s, TABLE_X, cur_y, TABLE_W, DATA_H, bg)
                if not val:
                    _text(s, TABLE_X + 0.08, cur_y, TABLE_W - 0.08, DATA_H,
                          "• " + (row[0] or ""), 9, C_INK)
                else:
                    pW = TABLE_W * 0.54
                    _text(s, TABLE_X + 0.06, cur_y, pW - 0.06, DATA_H, row[0] or "", 9, C_MUTED)
                    _text(s, TABLE_X + pW, cur_y, TABLE_W - pW - 0.06, DATA_H, val, 9, C_INK, bold=True)
                cur_y += DATA_H

    def _table(block, brand, name):
        s = _slide()
        _header(s, brand)
        _machine_name(s, name)
        _text(s, 0.2, CON_Y, 9.6, 0.34, block.get("title") or "", 12, C_INK, bold=True)
        rows = [r for r in (block.get("rows") or []) if r and (r[0] or (len(r) > 1 and r[1]))]
        if not rows:
            return
        single = all((len(r) < 2 or not r[1]) for r in rows)
        TABLE_Y = CON_Y + 0.38
        avail_h = H - TABLE_Y - 0.08
        head_h = 0.30
        row_h = min(0.285, (avail_h - head_h) / min(len(rows), 14))
        display = rows[: max(1, int((avail_h - head_h) / row_h))]
        pW = 9.6 if single else 5.2
        _rect(s, 0.2, TABLE_Y, 9.6, head_h, C_DARK)
        if single:
            _text(s, 0.28, TABLE_Y, 9.44, head_h, "НАИМЕНОВАНИЕ", 8, C_YELLOW, bold=True)
        else:
            _text(s, 0.28, TABLE_Y, pW - 0.08, head_h, "НАИМЕНОВАНИЕ / ПАРАМЕТР", 8, C_YELLOW, bold=True)
            _text(s, 0.2 + pW + 0.08, TABLE_Y, 9.6 - pW - 0.16, head_h, "ЗНАЧЕНИЕ", 8, C_YELLOW, bold=True)
        cur_y = TABLE_Y + head_h
        for i, row in enumerate(display):
            bg = C_EVEN if i % 2 == 0 else C_ODD
            _rect(s, 0.2, cur_y, 9.6, row_h, bg)
            if single:
                _text(s, 0.28, cur_y, 9.44, row_h, str(row[0] or ""), 10, C_INK)
            else:
                _text(s, 0.28, cur_y, pW - 0.08, row_h, str(row[0] or ""), 10, C_MUTED)
                _text(s, 0.2 + pW + 0.08, cur_y, 9.6 - pW - 0.16, row_h,
                      str(row[1] if len(row) > 1 else ""), 10, C_INK, bold=True)
            cur_y += row_h

    def _photo(block, brand, name):
        s = _slide()
        _header(s, brand)
        _machine_name(s, name)
        _text(s, 0.2, CON_Y, 9.6, 0.34, block.get("title") or "", 12, C_INK, bold=True)
        img_y = CON_Y + 0.38
        img_h = H - img_y - 0.08
        blob = block.get("_image")
        if blob:
            _image_contain(s, blob, 0.5, img_y, 9, img_h)
        else:
            _placeholder(s, 0.5, img_y, 9, img_h)

    def _text_slide(block, brand, name):
        s = _slide()
        _header(s, brand)
        _machine_name(s, name)
        _text(s, 0.2, CON_Y, 9.6, 0.34, block.get("title") or "", 12, C_INK, bold=True)
        _text(s, 0.2, CON_Y + 0.38, 9.6, H - CON_Y - 0.46, block.get("text") or "", 11, C_INK,
              anchor=MSO_ANCHOR.TOP)

    def _price(d, brand, name, manager, phone, trusted):
        s = _slide()
        _header(s, brand)
        _machine_name(s, name)
        BOX_Y, BOX_H, GAP = CON_Y, 1.30, 0.15
        BOX_W = (W - GAP * 4) / 3
        boxes = [("ГАРАНТИЯ", d.get("warranty") or "—"),
                 ("НАЛИЧИЕ / СРОК ПОСТАВКИ", d.get("availability") or "—"),
                 ("СТОИМОСТЬ", d.get("price") or "—")]
        for i, (label, value) in enumerate(boxes):
            bx = GAP + i * (BOX_W + GAP)
            _rect(s, bx, BOX_Y, BOX_W, BOX_H, C_SOFT, line=C_BORDER, line_pt=1)
            _rect(s, bx, BOX_Y, BOX_W, 0.06, C_YELLOW)
            _text(s, bx + 0.12, BOX_Y + 0.10, BOX_W - 0.24, 0.28, label, 8, C_INK, bold=True)
            _text(s, bx + 0.12, BOX_Y + 0.40, BOX_W - 0.24, BOX_H - 0.50, value, 10, C_INK,
                  anchor=MSO_ANCHOR.TOP)
        PAY_Y, PAY_W = BOX_Y + BOX_H + 0.14, 6.3
        _rect(s, GAP, PAY_Y, PAY_W, 0.25, C_DARK)
        _text(s, GAP + 0.10, PAY_Y, PAY_W, 0.25, "УСЛОВИЯ ОПЛАТЫ", 8, C_YELLOW, bold=True)
        terms = d.get("payment_terms")
        pay = "\n".join(terms) if isinstance(terms, list) else str(terms or "")
        _text(s, GAP, PAY_Y + 0.27, PAY_W, 0.68, pay, 9, C_INK, anchor=MSO_ANCHOR.TOP)
        CX = GAP + PAY_W + GAP
        CW = W - CX - GAP
        _rect(s, CX, PAY_Y, CW, 1.0, C_YELLOW)
        _text(s, CX, PAY_Y + 0.07, CW, 0.24, "Ваш менеджер", 8, C_INK, align=PP_ALIGN.CENTER)
        _text(s, CX, PAY_Y + 0.30, CW, 0.33, manager or "", 12, C_INK, bold=True, align=PP_ALIGN.CENTER)
        _text(s, CX, PAY_Y + 0.63, CW, 0.30, phone or "", 11, C_INK, align=PP_ALIGN.CENTER)
        TY = PAY_Y + 1.08
        TH = H - TY - 0.06
        _rect(s, 0, TY, W, TH, C_TRUST_BG)
        _text(s, 0.2, TY + 0.05, 2.5, 0.24, "НАМ ДОВЕРЯЮТ:", 8, C_INK, bold=True)
        _text(s, 0.2, TY + 0.30, 9.6, TH - 0.35, trusted or DEFAULT_TRUSTED, 8, C_TRUST_TX,
              anchor=MSO_ANCHOR.TOP)

    name = data.get("name") or ""
    brand = data.get("brand") or ""
    builders = {
        "title": lambda b: _title(b, brand, data.get("client_name")),
        "split": lambda b: _split(b, brand, name),
        "table": lambda b: _table(b, brand, name),
        "photo": lambda b: _photo(b, brand, name),
        "text": lambda b: _text_slide(b, brand, name),
    }
    for block in data.get("blocks") or []:
        fn = builders.get((block.get("type") or "").lower())
        if fn:
            fn(block)
    _price(data, brand, name, data.get("manager"), data.get("phone"), data.get("trusted_by"))

    out = io.BytesIO()
    prs.save(out)
    return out.getvalue()
