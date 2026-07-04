"""Issue #19 — единый фирменный стиль DOCX (цвета + OOXML-хелперы).

Убирает дублирование ``shade()`` и брендовых цветов, которые были скопированы
в docgen.py и reports.py (по 3-4 копии).
"""
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

# Фирменная гамма «Ремтехники»: жёлтый / чёрный / бледно-жёлтая полоса
YELLOW = "FFCB05"   # титульная плашка, акцент
DARK = "1A1A1A"     # шапки таблиц, текст
BAND = "FFF6D5"     # бледно-жёлтая полоса чередования строк


def shade(cell, color: str) -> None:
    """Заливка ячейки таблицы Word фоновым цветом (OOXML ``w:shd``)."""
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), color)
    tc_pr.append(shd)
