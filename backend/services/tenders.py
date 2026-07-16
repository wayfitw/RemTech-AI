"""Issue #35 (TASK-0801, EPIC-08) — поиск закупок на ЕИС zakupki.gov.ru.

Источник — страница расширенного поиска ЕИС (44-ФЗ/223-ФЗ), аккаунт не требуется.
ЕИС убрал RSS-выгрузку (results.rss → 404), поэтому парсим HTML-выдачу results.html.
Сетевой доступ идёт через SSRF-контур (services.websearch.fetch_raw, харднинг #8);
для росгос-домена доверяем корням Минцифры (websearch, #35 — иначе TLS-верификация
падает). Ничего не выдумываем: пустой результат и недоступность возвращаются честно.

Фильтры: ключевые слова и бюджет уходят в запрос ЕИС (server-side), регион и
заказчик дофильтровываются по тексту карточки (client-side) — сопоставление
регионов с кодами КЛАДР ЕИС вынесено в отдельную задачу.
"""
from __future__ import annotations

import html as _html
import re
from dataclasses import asdict, dataclass
from urllib.parse import urlencode

from services import websearch

EIS_SEARCH = "https://zakupki.gov.ru/epz/order/extendedsearch/results.html"
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
    """Собирает URL HTML-выдачи расширенного поиска ЕИС. Ключевые слова и бюджет —
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
    return f"{EIS_SEARCH}?{urlencode(q)}"


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
    s = re.sub(r"[^\d.,]", "", s)   # убираем ₽/буквы/сущности — остаются цифры и разделители
    # разделитель тысяч/копеек: убираем разделители тысяч, запятую-копейки → точка
    s = re.sub(r"(?<=\d)[.,](?=\d{3}\b)", "", s)   # тысячи
    s = s.replace(",", ".")
    try:
        return round(float(s), 2)
    except ValueError:
        return None


def _clean(s: str) -> str:
    """Снимает теги и HTML-сущности, схлопывает пробелы."""
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


# Карточка результата на странице ЕИС и её поля (классы registry-entry__*).
_CARD_SPLIT = re.compile(r"search-registry-entry-block")
_NUM_A_RE = re.compile(
    r"registry-entry__header-mid__number.*?<a[^>]*href=\"([^\"]+)\"[^>]*>(.*?)</a>", re.S)
_NAME_RE = re.compile(r"registry-entry__body-value[^>]*>(.*?)</div>", re.S)
_ORG_RE = re.compile(r"registry-entry__body-href[^>]*>(.*?)</a>", re.S)
_PRICE_BLOCK_RE = re.compile(r"price-block__value[^>]*>(.*?)</div>", re.S)
# признак того, что это действительно страница выдачи ЕИС (а не мусор/ошибка)
_EIS_MARKER_RE = re.compile(r"registry-entry|extendedsearch|search-registry", re.I)


def parse_eis_html(html_text: str) -> list[Tender]:
    """Парсит HTML-выдачу расширенного поиска ЕИС в список карточек. Толерантен к
    отсутствию отдельных полей; невалидный/непохожий на ЕИС ответ → TenderSourceError."""
    if not _EIS_MARKER_RE.search(html_text or ""):
        raise TenderSourceError("некорректный ответ источника (не страница ЕИС)")

    out: list[Tender] = []
    for block in _CARD_SPLIT.split(html_text)[1:]:
        num_m = _NUM_A_RE.search(block)
        link = _html.unescape(num_m.group(1).strip()) if num_m else ""
        raw_num = _clean(num_m.group(2)) if num_m else ""
        m = _NUM_RE.search(raw_num) or _NUM_LINK_RE.search(link)
        number = m.group(1) if m else re.sub(r"\D", "", raw_num)

        name_m = _NAME_RE.search(block)
        name = _clean(name_m.group(1)) if name_m else ""

        org_m = _ORG_RE.search(block)
        customer = _clean(org_m.group(1)) if org_m else ""

        price_m = _PRICE_BLOCK_RE.search(block)
        price = _to_price(_clean(price_m.group(1))) if price_m else None

        dm = _DEADLINE_RE.search(_clean(block))
        deadline = dm.group(1).strip() if dm else ""

        if number or name:   # пустые «хвосты» split не добавляем
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


@dataclass
class ProcurementCard:
    subject: str
    customer: str
    price: float | None
    deadline: str
    requirements: str        # текст блока требований к участникам (как в источнике)
    link: str
    missing: list[str]       # какие поля не удалось извлечь (не выдумываем)


_SUBJECT_RE = re.compile(
    r"(?:Наименование объекта закупки|Предмет(?: контракта| закупки)?|Объект закупки)"
    r"[:\s]*(.+?)(?:\n|Заказчик|Начальн|$)", re.IGNORECASE | re.DOTALL)
_REQ_RE = re.compile(
    r"Требовани[яе] к участникам[^:]*[:\s]*(.+?)"
    r"(?:\n\s*\n|Дата|Срок подачи|Обеспечение|Порядок|$)", re.IGNORECASE | re.DOTALL)


def extract_procurement(text: str, link: str = "") -> ProcurementCard:
    """Извлекает из текста карточки/извещения ЕИС предмет, заказчика, НМЦК, срок и
    блок требований к участникам. Не найденные поля попадают в missing (без
    домысливания). Работает и по тексту страницы-извещения, и по переданной карточке."""
    def _first(rx, flags=re.IGNORECASE | re.DOTALL):
        m = re.search(rx, text, flags) if isinstance(rx, str) else rx.search(text)
        return m.group(1).strip() if m else ""

    subj = _first(_SUBJECT_RE)
    cust = _first(_CUST_RE)
    pm = _PRICE_RE.search(text)
    price = _to_price(pm.group(1)) if pm else None
    dm = _DEADLINE_RE.search(text)
    deadline = dm.group(1).strip() if dm else ""
    req = re.sub(r"\s+\n", "\n", _first(_REQ_RE)).strip()

    missing = []
    if not subj:
        missing.append("предмет закупки")
    if not cust:
        missing.append("заказчик")
    if price is None:
        missing.append("НМЦК")
    if not deadline:
        missing.append("срок подачи заявок")
    if not req:
        missing.append("требования к участникам")

    return ProcurementCard(subject=re.sub(r"\s+", " ", subj), customer=re.sub(r"\s+", " ", cust),
                           price=price, deadline=deadline, requirements=req,
                           link=link, missing=missing)


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

    items = parse_eis_html(xml_text)
    items = apply_filters(items, region, customer, budget_min, budget_max)
    return [asdict(t) for t in items[:limit]]
