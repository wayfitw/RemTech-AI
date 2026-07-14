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
_MAX_AGE = settings.jwt_ttl_hours * 3600


def issue_csrf() -> str:
    return secrets.token_urlsafe(24)


def set_auth_cookies(response: Response, token: str, csrf: str) -> None:
    """access-токен — httpOnly (JS не читает), CSRF — читаемый (double-submit)."""
    common = {"max_age": _MAX_AGE, "secure": settings.cookie_secure,
              "samesite": "strict", "path": "/"}
    response.set_cookie(settings.auth_cookie_name, token, httponly=True, **common)
    response.set_cookie(settings.csrf_cookie_name, csrf, httponly=False, **common)


def clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.auth_cookie_name, path="/", samesite="strict")
    response.delete_cookie(settings.csrf_cookie_name, path="/", samesite="strict")


def token_from_cookie(request: Request) -> str | None:
    return request.cookies.get(settings.auth_cookie_name)


def csrf_ok(request: Request) -> bool:
    """Double-submit: заголовок X-CSRF-Token должен совпасть с CSRF-cookie."""
    header = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(settings.csrf_cookie_name, "")
    return bool(header) and bool(cookie) and secrets.compare_digest(header, cookie)
