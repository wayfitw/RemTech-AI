"""TASK-0606 (#46, EPIC-06) — сбор объявлений о запчастях с Авито и Дром.

Копим историю по позиции (цена при первом показе, текущая цена, дата публикации,
даты первого/последнего показа и снятия) — на этих данных строится аналитика спроса
для закупки (отчёт — отдельная TASK-0607).

Ответственный сбор (оговорка задачи «согласовать допустимость и частоту»):
  * выключено по умолчанию — включается флагом PARTS_PARSE_ENABLED;
  * перед каждым хостом проверяется robots.txt, Disallow уважается (обхода защит нет);
  * пауза между запросами (PARTS_REQUEST_DELAY_SECONDS), честный User-Agent;
  * сеть — только через SSRF-контур websearch.fetch_raw.

Устойчивость: недоступность площадки, антибот-ответ или изменившаяся разметка не
роняют конвейер — прогон возвращает список ошибок и продолжает с остальными
запросами (данные, собранные ранее, остаются в БД).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import time
import urllib.parse
from urllib.robotparser import RobotFileParser

from app.config import get_settings
from app.logging_config import get_logger
from services import websearch

log = get_logger("remtech.parts")

SOURCES = ("avito", "drom")
_ROBOTS_CACHE: dict[str, RobotFileParser | None] = {}

_HOSTS = {"avito": "https://www.avito.ru", "drom": "https://baza.drom.ru"}


class SourceUnavailable(RuntimeError):
    """Площадка недоступна: сеть, антибот-ответ, запрет robots.txt или пустая выдача."""


class LayoutChanged(RuntimeError):
    """Страница загрузилась, но разметка не распознана — вероятно, площадка её сменила."""


# ── доступ к площадке ────────────────────────────────────────────────────────

def search_url(source: str, query: str, region: str = "") -> str:
    """URL страницы выдачи по ключевым словам/артикулу."""
    q = urllib.parse.quote_plus(query.strip())
    if source == "avito":
        path = f"/{urllib.parse.quote(region.strip().lower())}" if region.strip() else "/rossiya"
        return f"{_HOSTS['avito']}{path}?q={q}"
    if source == "drom":
        return f"{_HOSTS['drom']}/search/?query={q}"
    raise ValueError(f"неизвестный источник: {source}")


def robots_allows(url: str, user_agent: str = "*") -> bool:
    """Проверяет robots.txt площадки. Недоступен robots — считаем, что нельзя
    (безопасное умолчание: не парсим то, чего не разрешили явно)."""
    parts = urllib.parse.urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    if origin not in _ROBOTS_CACHE:
        rp = RobotFileParser()
        try:
            body = websearch.fetch_raw(f"{origin}/robots.txt")
            rp.parse(body.splitlines())
            _ROBOTS_CACHE[origin] = rp
        except Exception as e:                     # noqa: BLE001 — любая ошибка → запрет
            log.warning("robots.txt недоступен для %s: %s", origin, e)
            _ROBOTS_CACHE[origin] = None
    rp = _ROBOTS_CACHE[origin]
    if rp is None:
        return False
    return rp.can_fetch(user_agent, url)


def fetch_html(url: str) -> str:
    """Загружает страницу выдачи через SSRF-контур; ошибки → SourceUnavailable."""
    try:
        html = websearch.fetch_raw(url)
    except Exception as e:                         # noqa: BLE001 — сеть/SSRF/таймаут
        raise SourceUnavailable(f"не удалось загрузить {url}: {e}") from e
    low = html.lower()
    # Типичные антибот-заглушки — не пытаемся их обходить, честно сообщаем.
    if len(html) < 500 or "captcha" in low or "доступ ограничен" in low:
        raise SourceUnavailable("площадка вернула проверку/ограничение доступа")
    return html


# ── разбор разметки ──────────────────────────────────────────────────────────

def _to_price(raw) -> int | None:
    if raw is None:
        return None
    digits = re.sub(r"[^\d]", "", str(raw))
    return int(digits) if digits else None


def _from_json_ld(html: str, source: str) -> list[dict]:
    """Первый (самый устойчивый) путь: разметка schema.org в <script type=ld+json>."""
    out = []
    for block in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(block.strip())
        except Exception:                          # noqa: BLE001 — битый JSON пропускаем
            continue
        items = data.get("itemListElement") if isinstance(data, dict) else None
        if not isinstance(items, list):
            continue
        for el in items:
            node = el.get("item") if isinstance(el, dict) else None
            if not isinstance(node, dict):
                continue
            url = str(node.get("url") or "")
            offers = node.get("offers") or {}
            price = _to_price(offers.get("price") if isinstance(offers, dict) else None)
            ext = _external_id(url, source)
            if not ext:
                continue
            out.append({"external_id": ext, "title": str(node.get("name") or "").strip(),
                        "price": price, "url": url, "published_at": None})
    return out


def _external_id(url: str, source: str) -> str:
    """id объявления из ссылки: Авито — хвост _123456789, Дром — /12345678.html."""
    if not url:
        return ""
    if source == "avito":
        m = re.search(r"_(\d{6,})(?:\?|$)", url)
        return m.group(1) if m else ""
    m = re.search(r"/(\d{6,})\.html", url)
    return m.group(1) if m else ""


def parse_avito(html: str) -> list[dict]:
    """Объявления Авито: JSON-LD → data-marker-разметка. Ничего не нашли → LayoutChanged."""
    items = _from_json_ld(html, "avito")
    if items:
        return items
    for block in re.findall(r'<div[^>]+data-marker="item"[^>]*>(.*?)</div>\s*</div>', html, re.S):
        m_url = re.search(r'href="(/[^"]+_(\d{6,}))"', block)
        if not m_url:
            continue
        title = re.search(r'data-marker="item-title"[^>]*>(?:<[^>]+>)*([^<]+)', block)
        price = re.search(r'data-marker="item-price"[^>]*content="(\d+)"', block) or \
            re.search(r'itemprop="price"[^>]*content="(\d+)"', block)
        items.append({
            "external_id": m_url.group(2),
            "title": (title.group(1).strip() if title else ""),
            "price": _to_price(price.group(1)) if price else None,
            "url": urllib.parse.urljoin(_HOSTS["avito"], m_url.group(1)),
            "published_at": None,
        })
    if not items:
        raise LayoutChanged("Авито: объявления не распознаны")
    return items


def parse_drom(html: str) -> list[dict]:
    """Объявления Дром: JSON-LD → ссылки вида /<id>.html с ценой рядом."""
    items = _from_json_ld(html, "drom")
    if items:
        return items
    for block in re.findall(r'<a[^>]+href="(https?://[^"]+/(\d{6,})\.html)"[^>]*>(.*?)</a>',
                            html, re.S):
        url, ext, inner = block
        title = re.sub(r"<[^>]+>", " ", inner)
        title = re.sub(r"\s+", " ", title).strip()
        tail = html[html.find(url):][:1500]
        price = re.search(r'data-price="(\d+)"', tail) or \
            re.search(r'(\d[\d\s ]{3,})\s*(?:₽|руб)', tail)
        items.append({
            "external_id": ext,
            "title": title,
            "price": _to_price(price.group(1)) if price else None,
            "url": url,
            "published_at": None,
        })
    if not items:
        raise LayoutChanged("Дром: объявления не распознаны")
    return items


_PARSERS = {"avito": parse_avito, "drom": parse_drom}


def collect(source: str, query: str, region: str = "", fetch=None) -> list[dict]:
    """Одна выдача площадки → список объявлений. fetch инъектируется в тестах.
    Бросает SourceUnavailable (в т.ч. при запрете robots) или LayoutChanged."""
    if source not in _PARSERS:
        raise ValueError(f"неизвестный источник: {source}")
    url = search_url(source, query, region)
    settings = get_settings()
    if fetch is None:
        if not robots_allows(url, settings.parts_user_agent):
            raise SourceUnavailable(f"robots.txt площадки запрещает сбор: {url}")
        time.sleep(max(0.0, float(settings.parts_request_delay_seconds)))
        html = fetch_html(url)
    else:
        html = fetch(url)
    rows = _PARSERS[source](html)
    for r in rows:
        r["source"] = source
        r["region"] = region
    return rows


# ── периодический прогон ─────────────────────────────────────────────────────

async def poll_once(s, *, fetch=None, require_enabled: bool = True, now=None) -> dict:
    """Один проход по активным запросам: новые объявления добавляются, известные
    обновляются (цена/last_seen), пропавшие из выдачи помечаются снятыми (closed_at).

    Возвращает {'new', 'updated', 'closed', 'errors': [...], 'skipped': str|None}.
    Недоступность источника не роняет прогон — ошибка копится в errors.
    """
    from app import repositories as repo

    settings = get_settings()
    if require_enabled and not settings.parts_parse_enabled:
        return {"new": 0, "updated": 0, "closed": 0, "errors": [], "skipped": "disabled"}

    queries = await repo.list_part_queries(s, only_active=True)
    if not queries:
        return {"new": 0, "updated": 0, "closed": 0, "errors": [], "skipped": "no_queries"}

    now = now or dt.datetime.now(dt.timezone.utc)
    new = updated = closed = 0
    errors: list[str] = []

    for q in queries:
        targets = SOURCES if (q.source or "all") == "all" else (q.source,)
        for source in targets:
            try:
                rows = collect(source, q.query, q.region or "", fetch=fetch)
            except (SourceUnavailable, LayoutChanged) as e:
                errors.append(f"{source} «{q.query}»: {e}")
                log.warning("parts poll: %s", errors[-1])
                continue                       # остальные запросы обрабатываем дальше
            except Exception as e:             # noqa: BLE001 — неожиданная ошибка тоже не роняет
                errors.append(f"{source} «{q.query}»: непредвиденная ошибка: {e}")
                log.exception("parts poll failed: %s / %s", source, q.query)
                continue

            seen_ids = []
            for row in rows:
                ext = str(row.get("external_id") or "").strip()
                if not ext:
                    continue                   # без id дедуп невозможен
                seen_ids.append(ext)
                created = await repo.upsert_part_listing(
                    s, source=source, external_id=ext, query_id=q.id,
                    title=row.get("title") or "", url=row.get("url") or "",
                    region=q.region or "", price=row.get("price"),
                    published_at=row.get("published_at"), now=now)
                new += int(created)
                updated += int(not created)
            # Пропали из выдачи → сняты (по ним считается скорость реализации)
            closed += await repo.close_missing_part_listings(
                s, source=source, query_id=q.id, seen_ids=seen_ids, now=now)

    await s.commit()
    return {"new": new, "updated": updated, "closed": closed,
            "errors": errors, "skipped": None}
