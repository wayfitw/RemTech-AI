"""Issue #35 (TASK-0801) — поиск закупок на ЕИС: парсинг HTML, фильтры, RBAC, отказы."""
import pytest

from agent.registry import role_can_use_tool
from services import tenders, websearch


def _card(num, name, customer, price_html, deadline):
    price_block = (f'<div class="price-block__value">{price_html}</div>' if price_html else "")
    return f'''
    <div class="search-registry-entry-block box-shadow-search-input">
      <div class="registry-entry__header-mid__number">
        <a href="https://zakupki.gov.ru/epz/order/notice/ea20/view/common-info.html?regNumber={num}">№ {num}</a>
      </div>
      <div class="registry-entry__body-value">{name}</div>
      <a class="registry-entry__body-href">{customer}</a>
      {price_block}
      <div class="data-block__value">Окончание подачи заявок {deadline}</div>
    </div>'''


# Реалистичная HTML-выдача расширенного поиска ЕИС (3 карточки).
FIXTURE = "<html><body>" + "".join([
    _card("0173200001424001234", "Поставка экскаватора XCMG", "ГБУ «Автодороги»",
          "5 000 000,00 &#8381;", "20.07.2026 10:00"),
    _card("0173200001424005678", "Поставка фронтального погрузчика (Красноярский край)",
          "МКУ «УКС»", "12 000 000,00 &#8381;", "22.07.2026 09:00"),
    _card("0173200001424009999", "Поставка запасных частей", "ООО «Ромашка»",
          "", "25.07.2026"),
]) + "</body></html>"


def test_parse_eis_html_extracts_fields():
    items = tenders.parse_eis_html(FIXTURE)
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
    items = tenders.parse_eis_html(FIXTURE)
    res = tenders.apply_filters(items, budget_max=10_000_000)
    nums = {t.number for t in res}
    assert "0173200001424001234" in nums     # 5 млн — прошёл
    assert "0173200001424005678" not in nums  # 12 млн — отсеян
    assert "0173200001424009999" in nums      # цена неизвестна — оставлен


def test_filter_by_region_and_customer():
    items = tenders.parse_eis_html(FIXTURE)
    assert {t.number for t in tenders.apply_filters(items, region="Красноярск")} == {"0173200001424005678"}
    assert {t.number for t in tenders.apply_filters(items, customer="Ромашка")} == {"0173200001424009999"}


def test_build_search_url_has_keywords_and_budget():
    url = tenders.build_search_url("экскаватор XCMG", budget_min=1_000_000, budget_max=9_000_000)
    assert url.startswith(tenders.EIS_SEARCH) and "results.html" in url
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
    # ответ не похож на страницу ЕИС (нет registry-entry) → честный отказ
    with pytest.raises(tenders.TenderSourceError):
        tenders.search_tenders("x", fetch=lambda url: "<html>ошибка 404</html>")


def test_empty_results_page_returns_empty():
    # валидная страница ЕИС без карточек — пустой список, не ошибка
    page = '<html><body><div class="search-registry">Ничего не найдено</div></body></html>'
    assert tenders.parse_eis_html(page) == []


def test_rbac_tool_gated_by_role():
    # доступ только закупкам/руководству; admin — всегда; прочие — нет
    assert role_can_use_tool("закупки", "search_tenders") is True
    assert role_can_use_tool("руководство", "search_tenders") is True
    assert role_can_use_tool("admin", "search_tenders") is True
    assert role_can_use_tool("user", "search_tenders") is False
    assert role_can_use_tool("менеджер", "search_tenders") is False
    # инструменты без ограничений доступны всем ролям
    assert role_can_use_tool("user", "read_url") is True


def test_gov_host_detection():
    # росгос-домены → расширенный CA-бандл; прочие — стандартная проверка (#35)
    assert websearch._is_gov_host("zakupki.gov.ru") is True
    assert websearch._is_gov_host("nuc-cdp.digital.gov.ru") is True
    assert websearch._is_gov_host("example.com") is False
    assert websearch._is_gov_host("notgov.ru") is False
