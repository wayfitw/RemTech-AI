"""Issue #4 — хранение access-токена в httpOnly-cookie + CSRF (double-submit).

httpOnly-cookie недоступна JavaScript, поэтому украсть токен через XSS нельзя
(в отличие от localStorage). Так как cookie шлётся браузером автоматически,
добавляется защита от CSRF: SameSite=Strict + двойная отправка CSRF-токена
(читаемый cookie, который клиент эхом кладёт в заголовок X-CSRF-Token).
"""
import secrets

from fastapi import Request, Response

from app.config import get_settings

settings = get_settings()
_ACCESS_AGE = settings.access_ttl_minutes * 60
_REFRESH_AGE = settings.refresh_ttl_hours * 3600
_REFRESH_PATH = "/api/refresh"   # refresh-cookie шлётся только на эндпоинт обновления


def issue_csrf() -> str:
    return secrets.token_urlsafe(24)


def set_auth_cookies(response: Response, access: str, refresh: str, csrf: str) -> None:
    """#38 — access (короткий, httpOnly, весь сайт), refresh (долгий, httpOnly, только
    /api/refresh — меньше поверхность), CSRF (читаемый, double-submit)."""
    base = {"secure": settings.cookie_secure, "samesite": "strict"}
    response.set_cookie(settings.auth_cookie_name, access, httponly=True,
                        max_age=_ACCESS_AGE, path="/", **base)
    response.set_cookie(settings.refresh_cookie_name, refresh, httponly=True,
                        max_age=_REFRESH_AGE, path=_REFRESH_PATH, **base)
    response.set_cookie(settings.csrf_cookie_name, csrf, httponly=False,
                        max_age=_REFRESH_AGE, path="/", **base)


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.auth_cookie_name, path="/", samesite="strict")
    response.delete_cookie(settings.refresh_cookie_name, path=_REFRESH_PATH, samesite="strict")
    response.delete_cookie(settings.csrf_cookie_name, path="/", samesite="strict")


def token_from_cookie(request: Request) -> str | None:
    return request.cookies.get(settings.auth_cookie_name)


def csrf_ok(request: Request) -> bool:
    """Double-submit: заголовок X-CSRF-Token должен совпасть с CSRF-cookie."""
    header = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(settings.csrf_cookie_name, "")
    return bool(header) and bool(cookie) and secrets.compare_digest(header, cookie)
