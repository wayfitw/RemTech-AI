"""Чтение веб-страниц (read_url) с защитой от SSRF.
Веб-поиск выполняется на стороне Anthropic (серверный инструмент web_search)."""
import functools
import glob
import ipaddress
import os
import socket
import ssl
from urllib.parse import urlparse, urlunparse

# Росгос-домены с сертификатами национального УЦ Минцифры («Russian Trusted CA»),
# которого нет в стандартном хранилище. Для них — расширенный CA-бандл (issue #35).
_GOV_SUFFIXES = (".gov.ru", ".voskhod.ru")
_CERTS_DIR = os.path.join(os.path.dirname(__file__), "..", "certs")


def _is_gov_host(host: str) -> bool:
    h = (host or "").lower()
    return h == "gov.ru" or any(h.endswith(s) for s in _GOV_SUFFIXES)


@functools.lru_cache(maxsize=1)
def _gov_ca_context() -> "ssl.SSLContext":
    """TLS-контекст = стандартные корни (certifi) + корни «Russian Trusted CA».
    Проверка сертификатов ОСТАЁТСЯ включённой; доверие к нацУЦ расширяется только
    для росгос-доменов (см. _is_gov_host). Сертификаты — в backend/certs/*.pem."""
    import certifi
    ctx = ssl.create_default_context(cafile=certifi.where())
    for pem in sorted(glob.glob(os.path.join(_CERTS_DIR, "*.pem"))):
        try:
            ctx.load_verify_locations(cafile=pem)
        except ssl.SSLError:
            pass   # битый/неподходящий файл не должен ронять обычные запросы
    return ctx


def _ip_is_internal(ip: str) -> bool:
    """True, если адрес ведёт во внутреннюю сеть (loopback/private/link-local/reserved/…)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True   # не смогли разобрать — считаем небезопасным
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local
                or addr.is_reserved or addr.is_multicast or addr.is_unspecified)


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Разрешает только http/https на публичные адреса. Блокирует запросы
    к внутренним/приватным IP (loopback, private, link-local, метаданные облака)."""
    try:
        p = urlparse(url)
    except Exception:
        return False, "некорректная ссылка"
    if p.scheme not in ("http", "https"):
        return False, "разрешены только http и https"
    host = p.hostname
    if not host:
        return False, "не указан хост"
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return False, "не удалось разрешить адрес хоста"
    for info in infos:
        if _ip_is_internal(info[4][0]):
            return False, "доступ к внутренним адресам запрещён"
    return True, ""


_TIMEOUT = 10.0
_MAX_BYTES = 3_000_000
_MAX_HOPS = 3


class _UnsafeRedirect(Exception):
    pass


def _resolve_pinned_ip(host: str, port: int) -> str:
    """Резолвит хост ОДИН раз и возвращает публичный IP для подключения (issue #8).
    ВСЕ A/AAAA-записи обязаны быть публичными — иначе отказ. Подключаться будем
    именно к этому IP, чтобы между проверкой и запросом не произошёл DNS-rebinding."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except Exception:
        raise _UnsafeRedirect("не удалось разрешить адрес хоста")
    ip = None
    for info in infos:
        cand = info[4][0]
        if _ip_is_internal(cand):
            raise _UnsafeRedirect("адрес хоста ведёт во внутреннюю сеть")
        ip = ip or cand
    if not ip:
        raise _UnsafeRedirect("адрес хоста не разрешён")
    return ip


def _fetch_html(url: str) -> str:
    """Загружает HTML вручную с пиннингом IP и ревалидацией на каждом хопе редиректа
    (issue #8). Хост резолвится один раз, подключение идёт к проверенному IP
    (Host-заголовок сохраняется) — так httpx не перерезолвит хост на внутренний адрес.
    Плюс таймаут и лимит размера."""
    import httpx

    ua = {"User-Agent": "RemTechAI/1.0 (+internal)"}
    # Для росгос-доменов доверяем корням Минцифры (иначе CERTIFICATE_VERIFY_FAILED),
    # для остального — стандартная проверка. Контекст по хосту исходного URL (#35).
    verify = _gov_ca_context() if _is_gov_host(urlparse(url).hostname) else True
    with httpx.Client(follow_redirects=False, timeout=_TIMEOUT, headers=ua, verify=verify) as client:
        for _ in range(_MAX_HOPS + 1):
            p = urlparse(url)
            if p.scheme not in ("http", "https") or not p.hostname:
                raise _UnsafeRedirect("недопустимая ссылка")
            port = p.port or (443 if p.scheme == "https" else 80)
            ip = _resolve_pinned_ip(p.hostname, port)   # резолв один раз + проверка

            # URL с закреплённым IP; Host и SNI — исходный хост (TLS-сертификат валиден)
            netloc = (f"[{ip}]" if ":" in ip else ip) + (f":{p.port}" if p.port else "")
            ip_url = urlunparse((p.scheme, netloc, p.path or "/", p.params, p.query, ""))
            headers = {"Host": p.netloc}
            ext = {"sni_hostname": p.hostname} if p.scheme == "https" else {}

            with client.stream("GET", ip_url, headers=headers, extensions=ext) as r:
                if r.is_redirect:
                    loc = r.headers.get("location")
                    if not loc:
                        raise _UnsafeRedirect("редирект без адреса")
                    url = str(httpx.URL(url).join(loc))   # join против исходного (хостового) URL
                    continue
                chunks, size = [], 0
                for chunk in r.iter_bytes():
                    size += len(chunk)
                    if size > _MAX_BYTES:
                        break
                    chunks.append(chunk)
                return b"".join(chunks).decode(r.encoding or "utf-8", errors="replace")
        raise _UnsafeRedirect("слишком много редиректов")


class UnsafeUrl(Exception):
    """Ссылка не прошла SSRF-проверку либо источник недоступен."""


def fetch_raw(url: str) -> str:
    """Безопасно (SSRF-контур #8) загружает сырой ответ по URL и возвращает текст.
    В отличие от read_url НЕ прогоняет через trafilatura — нужно для RSS/XML/JSON
    (напр. выгрузки ЕИС, issue #35). Бросает UnsafeUrl при отказе/недоступности."""
    ok, reason = _is_safe_url(url)
    if not ok:
        raise UnsafeUrl(reason)
    try:
        return _fetch_html(url)
    except _UnsafeRedirect as e:
        raise UnsafeUrl(str(e)) from e


def read_url(url: str) -> str:
    ok, reason = _is_safe_url(url)
    if not ok:
        return f"Ссылка отклонена: {reason}."

    import trafilatura

    try:
        downloaded = _fetch_html(url)
    except _UnsafeRedirect as e:
        return f"Ссылка отклонена: {e}."
    except Exception:
        return "Не удалось загрузить страницу."
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
    if not text:
        return "Не удалось извлечь текст со страницы."
    return text[:8000]
