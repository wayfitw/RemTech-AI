"""Issue #35 (TASK-0801) — поиск закупок на ЕИС: парсинг, фильтры, RBAC, отказы."""
import pytest

from agent.registry import role_can_use_tool
from services import tenders, websearch

# Реалистичная RSS-выдача расширенного поиска ЕИС (3 карточки).
FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>№ 0173200001424001234 Поставка экскаватора XCMG</title>
    <link>https://zakupki.gov.ru/epz/order/notice/view.html?regNumber=0173200001424001234</link>
    <description>Заказчик: ГБУ «Автодороги». Начальная (максимальная) цена контракта: 5 000 000,00 российский рубль. Дата окончания подачи заявок: 20.07.2026 10:00</description>
  </item>
  <item>
    <title>№ 0173200001424005678 Поставка фронтального погрузчика (Красноярский край)</title>
    <link>https://zakupki.gov.ru/epz/order/notice/view.html?regNumber=0173200001424005678</link>
    <description>Заказчик: МКУ «УКС». Начальная (максимальная) цена контракта: 12 000 000,00 российский рубль. Дата окончания подачи заявок: 22.07.2026 09:00</description>
  </item>
  <item>
    <title>№ 0173200001424009999 Поставка запасных частей</title>
    <link>https://zakupki.gov.ru/epz/order/notice/view.html?regNumber=0173200001424009999</link>
    <description>Заказчик: ООО «Ромашка». Предмет: запчасти. Срок подачи заявок: 25.07.2026</description>
  </item>
</channel></rss>"""


def test_parse_eis_rss_extracts_fields():
    items = tenders.parse_eis_rss(FIXTURE)
    assert len(items) == 3
    a = items[0]
    assert a.number == "0173200001424001234"
    assert a.name == "Поставка экскаватора XCMG"
    assert "Автодороги" in a.customer
    assert a.price == 5_000_000.0
    assert a.deadline.startswith("20.07.2026")
    assert "regNumber=0173200001424001234" in a.link
    # у третьей карточки цена не указана — не выдумываем
    assert items[2].price is None


def test_filter_by_budget_keeps_unknown_price():
    items = tenders.parse_eis_rss(FIXTURE)
    res = tenders.apply_filters(items, budget_max=10_000_000)
    nums = {t.number for t in res}
    assert "0173200001424001234" in nums     # 5 млн — прошёл
    assert "0173200001424005678" not in nums  # 12 млн — отсеян
    assert "0173200001424009999" in nums      # цена неизвестна — оставлен


def test_filter_by_region_and_customer():
    items = tenders.parse_eis_rss(FIXTURE)
    assert {t.number for t in tenders.apply_filters(items, region="Красноярск")} == {"0173200001424005678"}
    assert {t.number for t in tenders.apply_filters(items, customer="Ромашка")} == {"0173200001424009999"}


def test_build_search_url_has_keywords_and_budget():
    url = tenders.build_search_url("экскаватор XCMG", budget_min=1_000_000, budget_max=9_000_000)
    assert url.startswith(tenders.EIS_RSS)
    assert "searchString=" in url and "fz44=on" in url
    assert "priceFromGeneral=1000000" in url and "priceToGeneral=9000000" in url


def test_search_tenders_end_to_end_with_injected_fetch():
    rows = tenders.search_tenders("экскаватор", budget_max=10_000_000,
                                  fetch=lambda url: FIXTURE)
    assert isinstance(rows, list) and rows and isinstance(rows[0], dict)
    assert rows[0]["number"] == "0173200001424001234"
    assert all(r["number"] != "0173200001424005678" for r in rows)  # 12 млн отфильтрован


def test_source_unavailable_raises():
    def boom_unsafe(url):
        raise websearch.UnsafeUrl("адрес хоста ведёт во внутреннюю сеть")
    with pytest.raises(tenders.TenderSourceError):
        tenders.search_tenders("x", fetch=boom_unsafe)

    def boom_net(url):
        raise TimeoutError("timed out")
    with pytest.raises(tenders.TenderSourceError):
        tenders.search_tenders("x", fetch=boom_net)


def test_malformed_source_raises():
    with pytest.raises(tenders.TenderSourceError):
        tenders.search_tenders("x", fetch=lambda url: "<not xml")


def test_rbac_tool_gated_by_role():
    # доступ только закупкам/руководству; admin — всегда; прочие — нет
    assert role_can_use_tool("закупки", "search_tenders") is True
    assert role_can_use_tool("руководство", "search_tenders") is True
    assert role_can_use_tool("admin", "search_tenders") is True
    assert role_can_use_tool("user", "search_tenders") is False
    assert role_can_use_tool("менеджер", "search_tenders") is False
    # инструменты без ограничений доступны всем ролям
    assert role_can_use_tool("user", "read_url") is True
