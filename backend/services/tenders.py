"""Issue #35 (TASK-0801, EPIC-08) — поиск закупок на ЕИС zakupki.gov.ru.

Источник версии 1 — открытая RSS-выгрузка расширенного поиска ЕИС (44-ФЗ/223-ФЗ),
аккаунт не требуется. Сетевой доступ идёт через SSRF-контур (services.websearch.
fetch_raw, харднинг #8). Ничего не выдумываем: пустой результат и недоступность
источника возвращаются честно.

Фильтры: ключевые слова и бюджет уходят в запрос ЕИС (server-side), регион и
заказчик дофильтровываются по тексту карточки (client-side) — сопоставление
регионов с кодами КЛАДР ЕИС вынесено в отдельную задачу.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from urllib.parse import urlencode

from services import websearch

EIS_RSS = "https://zakupki.gov.ru/epz/order/extendedsearch/results.rss"
MAX_RESULTS = 20


class TenderSourceError(Exception):
    """Источник ЕИС недоступен/не отвечает корректно."""


@dataclass
class Tender:
    number: str
    name: str
    customer: str
    price: float | None      # НМЦК, ₽ (None — не удалось извлечь)
    deadline: str            # срок подачи заявок (как в источнике)
    link: str


def build_search_url(keywords: str, budget_min: float | None = None,
                     budget_max: float | None = None) -> str:
    """Собирает URL RSS-выдачи расширенного поиска ЕИС. Ключевые слова и бюджет —
    параметры ЕИС; регион/заказчик фильтруются уже по результату (client-side)."""
    q = {
        "searchString": keywords or "",
        "morphology": "on",
        "fz44": "on",
        "fz223": "on",
        "sortBy": "UPDATE_DATE",
        "recordsPerPage": "_50",
        "pageNumber": "1",
    }
    if budget_min is not None:
        q["priceFromGeneral"] = str(int(budget_min))
    if budget_max is not None:
        q["priceToGeneral"] = str(int(budget_max))
    return f"{EIS_RSS}?{urlencode(q)}"


_NUM_RE = re.compile(r"№\s*([0-9]{6,})")
_NUM_LINK_RE = re.compile(r"regNumber=([0-9]{6,})")
_PRICE_RE = re.compile(r"цен[аы][^0-9]*([0-9][0-9\s .,]*[0-9])", re.IGNORECASE)
_CUST_RE = re.compile(
    r"Заказчик[:\s]*(.+?)\s*(?:Начальн|Цена|Сумма|Дата|Срок|$)", re.IGNORECASE | re.DOTALL)
_DEADLINE_RE = re.compile(
    r"(?:окончани[ея]|подачи заявок)[^0-9]*([0-9]{2}\.[0-9]{2}\.[0-9]{4}(?:\s[0-9]{2}:[0-9]{2})?)",
    re.IGNORECASE)


def _to_price(raw: str) -> float | None:
    s = raw.replace(" ", "").replace(" ", "")
    # разделитель тысяч/копеек: убираем разделители тысяч, запятую-копейки → точка
    s = re.sub(r"(?<=\d)[.,](?=\d{3}\b)", "", s)   # тысячи
    s = s.replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def parse_eis_rss(xml_text: str) -> list[Tender]:
    """Парсит RSS-выдачу ЕИС в список карточек. Толерантен к отсутствию полей."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise TenderSourceError(f"некорректный ответ источника: {e}") from e

    out: list[Tender] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        desc = (item.findtext("description") or "").strip()
        blob = f"{title}\n{desc}"

        m = _NUM_RE.search(title) or _NUM_RE.search(desc) or _NUM_LINK_RE.search(link)
        number = m.group(1) if m else ""
        # имя = заголовок без номерного префикса
        name = re.sub(r"^№?\s*[0-9]{6,}\s*", "", title).strip() or title

        cust = _CUST_RE.search(desc)
        customer = re.sub(r"\s+", " ", cust.group(1)).strip() if cust else ""

        pm = _PRICE_RE.search(blob)
        price = _to_price(pm.group(1)) if pm else None

        dm = _DEADLINE_RE.search(blob)
        deadline = dm.group(1).strip() if dm else ""

        out.append(Tender(number=number, name=name, customer=customer,
                          price=price, deadline=deadline, link=link))
    return out


def apply_filters(items: list[Tender], region: str = "", customer: str = "",
                  budget_min: float | None = None,
                  budget_max: float | None = None) -> list[Tender]:
    """Дофильтровывает результат по региону/заказчику (текст) и бюджету (по НМЦК).
    Позиции с неизвестной ценой по бюджету не отсеиваются (не выдумываем цену)."""
    reg = (region or "").strip().lower()
    cust = (customer or "").strip().lower()
    res = []
    for t in items:
        hay = f"{t.name} {t.customer}".lower()
        if reg and reg not in hay:
            continue
        if cust and cust not in t.customer.lower():
            continue
        if t.price is not None:
            if budget_min is not None and t.price < budget_min:
                continue
            if budget_max is not None and t.price > budget_max:
                continue
        res.append(t)
    return res


def search_tenders(keywords: str, region: str = "", customer: str = "",
                   budget_min: float | None = None, budget_max: float | None = None,
                   fetch=websearch.fetch_raw, limit: int = MAX_RESULTS) -> list[dict]:
    """Полный цикл: URL ЕИС → безопасный фетч → парсинг → фильтры. Возвращает
    список карточек (dict). Бросает TenderSourceError при недоступности источника."""
    url = build_search_url(keywords, budget_min, budget_max)
    try:
        xml_text = fetch(url)
    except websearch.UnsafeUrl as e:
        raise TenderSourceError(f"источник недоступен: {e}") from e
    except Exception as e:  # сетевые сбои/таймаут — честно наверх
        raise TenderSourceError(f"источник недоступен: {type(e).__name__}") from e

    items = parse_eis_rss(xml_text)
    items = apply_filters(items, region, customer, budget_min, budget_max)
    return [asdict(t) for t in items[:limit]]
