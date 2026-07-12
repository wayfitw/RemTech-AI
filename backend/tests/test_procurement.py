"""Issue #36 (TASK-0803) — предварительный анализ закупки: извлечение, честность, RBAC."""
from agent.registry import role_can_use_tool
from services import tenders

FULL = """Извещение об осуществлении закупки
Наименование объекта закупки: Поставка экскаватора XCMG XE215C
Заказчик: ГБУ «Автодороги»
Начальная (максимальная) цена контракта: 5 000 000,00 российский рубль
Требования к участникам: Единые требования по ст.31 44-ФЗ; наличие опыта поставки спецтехники; отсутствие в РНП.
Дата и время окончания срока подачи заявок: 20.07.2026 10:00
"""

INCOMPLETE = """Наименование объекта закупки: Поставка запасных частей
Заказчик: ООО «Ромашка»
"""


def test_extract_full_card():
    c = tenders.extract_procurement(FULL, link="https://zakupki.gov.ru/x")
    assert c.subject == "Поставка экскаватора XCMG XE215C"
    assert "Автодороги" in c.customer
    assert c.price == 5_000_000.0
    assert c.deadline.startswith("20.07.2026")
    assert "ст.31" in c.requirements and "РНП" in c.requirements
    assert c.link == "https://zakupki.gov.ru/x"
    assert c.missing == []          # всё извлечено — нечего домысливать


def test_extract_incomplete_flags_missing():
    c = tenders.extract_procurement(INCOMPLETE)
    assert c.subject and c.customer          # что есть — извлекли
    assert c.price is None
    # честно помечаем нехватку, не выдумываем
    assert "НМЦК" in c.missing
    assert "срок подачи заявок" in c.missing
    assert "требования к участникам" in c.missing


def test_extract_empty_text_all_missing():
    c = tenders.extract_procurement("случайный текст без полей")
    assert set(c.missing) == {"предмет закупки", "заказчик", "НМЦК",
                              "срок подачи заявок", "требования к участникам"}


def test_rbac_procurement_gated_by_role():
    assert role_can_use_tool("закупки", "analyze_procurement") is True
    assert role_can_use_tool("руководство", "analyze_procurement") is True
    assert role_can_use_tool("admin", "analyze_procurement") is True
    assert role_can_use_tool("user", "analyze_procurement") is False
