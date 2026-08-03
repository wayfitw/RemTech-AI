"""TASK-0606 (#46) — сбор объявлений о запчастях: парсинг фикстур разметки, дедуп
и история позиции, устойчивость к недоступности источника, robots.txt, RBAC."""
import pytest
from sqlalchemy import select

from agent.registry import role_can_use_tool
from app import repositories as repo
from app.models import PartListing
from services import parts_market as pm

AVITO_JSON_LD = """
<html><head>
<script type="application/ld+json">
{"itemListElement":[
 {"item":{"name":"Гидронасос XCMG XE215","url":"https://www.avito.ru/krasnoyarsk/zapchasti/gidronasos_777111222",
   "offers":{"price":"85000"}}},
 {"item":{"name":"Фильтр масляный XCMG","url":"https://www.avito.ru/krasnoyarsk/zapchasti/filtr_777333444",
   "offers":{"price":"2500"}}}
]}
</script></head><body>%s</body></html>
""" % ("наполнитель " * 100)

AVITO_MARKUP = """
<html><body>%s
<div data-marker="item">
  <a href="/krasnoyarsk/zapchasti/nasos_555666777"></a>
  <h3 data-marker="item-title"><span>Насос шестерённый LiuGong</span></h3>
  <meta data-marker="item-price" content="41000">
</div></div>
</body></html>
""" % ("наполнитель " * 100)

DROM_FIXTURE = """
<html><body>%s
<a href="https://baza.drom.ru/parts/888999000.html"><div>Турбина Cummins QSB6.7</div></a>
<span data-price="63000">63 000 ₽</span>
</body></html>
""" % ("наполнитель " * 100)


# ── парсинг фикстур разметки ─────────────────────────────────────────────────

def test_parse_avito_json_ld():
    rows = pm.parse_avito(AVITO_JSON_LD)
    assert len(rows) == 2
    first = rows[0]
    assert first["external_id"] == "777111222"
    assert "Гидронасос" in first["title"] and first["price"] == 85000


def test_parse_avito_data_marker_fallback():
    rows = pm.parse_avito(AVITO_MARKUP)
    assert len(rows) == 1
    assert rows[0]["external_id"] == "555666777"
    assert rows[0]["price"] == 41000
    assert rows[0]["url"].startswith("https://www.avito.ru/")


def test_parse_drom_fixture():
    rows = pm.parse_drom(DROM_FIXTURE)
    assert rows and rows[0]["external_id"] == "888999000"
    assert "Турбина" in rows[0]["title"] and rows[0]["price"] == 63000


def test_parse_layout_changed_degrades_clearly():
    """Разметка сменилась — понятная ошибка, а не тихий пустой результат."""
    with pytest.raises(pm.LayoutChanged):
        pm.parse_avito("<html><body>" + "ничего похожего " * 100 + "</body></html>")


def test_antibot_response_is_source_unavailable(monkeypatch):
    monkeypatch.setattr(pm.websearch, "fetch_raw", lambda url: "<html>CAPTCHA</html>")
    with pytest.raises(pm.SourceUnavailable):
        pm.fetch_html("https://www.avito.ru/rossiya?q=x")


def test_robots_disallow_blocks_collect(monkeypatch):
    """robots.txt запрещает — сбор не выполняется (обхода защит нет)."""
    pm._ROBOTS_CACHE.clear()
    monkeypatch.setattr(pm.websearch, "fetch_raw",
                        lambda url: "User-agent: *\nDisallow: /\n")
    with pytest.raises(pm.SourceUnavailable, match="robots"):
        pm.collect("avito", "гидронасос")


def test_robots_unavailable_defaults_to_deny(monkeypatch):
    """robots.txt недоступен → считаем, что нельзя (безопасное умолчание)."""
    pm._ROBOTS_CACHE.clear()

    def boom(url):
        raise RuntimeError("сеть недоступна")

    monkeypatch.setattr(pm.websearch, "fetch_raw", boom)
    assert pm.robots_allows("https://www.avito.ru/rossiya?q=x") is False


# ── прогон: дедуп, история, устойчивость ─────────────────────────────────────

async def _add_query(session, query="гидронасос XCMG"):
    q = await repo.add_part_query(session, query, "avito", "")
    await session.commit()
    return q


async def test_poll_collects_then_dedups_and_tracks_price(session):
    await _add_query(session)

    def fetch_first(url):
        return AVITO_JSON_LD

    r1 = await pm.poll_once(session, fetch=fetch_first, require_enabled=False)
    assert r1["new"] == 2 and r1["updated"] == 0 and r1["errors"] == []

    # второй прогон: те же объявления (одно подешевело) — дубли не создаются
    cheaper = AVITO_JSON_LD.replace('"price":"85000"', '"price":"79000"')
    r2 = await pm.poll_once(session, fetch=lambda url: cheaper, require_enabled=False)
    assert r2["new"] == 0 and r2["updated"] == 2      # дедуп по (source, external_id)

    rows = list(await session.scalars(select(PartListing).order_by(PartListing.id)))
    assert len(rows) == 2
    tracked = next(r for r in rows if r.external_id == "777111222")
    assert tracked.price == 79000 and tracked.price_initial == 85000   # история цены
    assert tracked.closed_at is None


async def test_poll_marks_listing_closed_when_gone(session):
    await _add_query(session)
    await pm.poll_once(session, fetch=lambda url: AVITO_JSON_LD, require_enabled=False)

    # во второй выдаче осталось только одно объявление → второе снято с продажи
    only_one = AVITO_JSON_LD.replace(
        ',\n {"item":{"name":"Фильтр масляный XCMG","url":"https://www.avito.ru/krasnoyarsk/zapchasti/filtr_777333444",\n   "offers":{"price":"2500"}}}', "")
    r = await pm.poll_once(session, fetch=lambda url: only_one, require_enabled=False)
    assert r["closed"] == 1

    gone = await session.scalar(
        select(PartListing).where(PartListing.external_id == "777333444"))
    assert gone.closed_at is not None                 # дата снятия — для скорости реализации


async def test_poll_source_unavailable_does_not_crash(session):
    """Площадка недоступна: прогон не падает, ошибка возвращается, ранее собранные
    объявления НЕ помечаются снятыми (иначе ложная статистика)."""
    await _add_query(session)
    await pm.poll_once(session, fetch=lambda url: AVITO_JSON_LD, require_enabled=False)

    def boom(url):
        raise pm.SourceUnavailable("площадка не отвечает")

    r = await pm.poll_once(session, fetch=boom, require_enabled=False)
    assert r["new"] == 0 and r["closed"] == 0 and len(r["errors"]) == 1
    assert "не отвечает" in r["errors"][0]
    alive = await session.scalar(
        select(PartListing).where(PartListing.external_id == "777111222"))
    assert alive.closed_at is None


async def test_poll_disabled_by_flag(session):
    await _add_query(session)

    def must_not_call(url):
        raise AssertionError("сбор не должен идти при выключенном флаге")

    r = await pm.poll_once(session, fetch=must_not_call, require_enabled=True)
    assert r["skipped"] == "disabled"


async def test_poll_without_queries(session):
    r = await pm.poll_once(session, fetch=lambda url: AVITO_JSON_LD, require_enabled=False)
    assert r["skipped"] == "no_queries"


async def test_part_query_crud(session):
    q = await repo.add_part_query(session, "фильтр XCMG", "drom", "")
    await session.commit()
    assert q is not None
    assert await repo.add_part_query(session, "фильтр XCMG", "drom", "") is None   # идемпотентно
    assert [r.query for r in await repo.list_part_queries(session)] == ["фильтр XCMG"]
    assert await repo.delete_part_query(session, "фильтр") == "фильтр XCMG"
    await session.commit()
    assert await repo.list_part_queries(session) == []


def test_search_url_and_external_id():
    assert "q=" in pm.search_url("avito", "гидронасос", "krasnoyarsk")
    assert pm.search_url("drom", "турбина").startswith("https://baza.drom.ru")
    assert pm._external_id("https://www.avito.ru/x/nasos_123456789", "avito") == "123456789"
    assert pm._external_id("https://baza.drom.ru/parts/987654321.html", "drom") == "987654321"


def test_parts_tools_rbac():
    for tool in ("add_part_query", "list_part_queries", "remove_part_query"):
        assert role_can_use_tool("закупки", tool) is True
        assert role_can_use_tool("руководство", tool) is True
        assert role_can_use_tool("admin", tool) is True
        assert role_can_use_tool("маркетинг", tool) is False

