"""Cutover Стадия 2 — тесты авторизации (pbkdf2, JWT, регистрация по приглашению)."""
from app import auth
from app import repositories as repo


def test_password_hash_verify():
    h = auth.hash_password("secret")
    assert "$" in h and h != "secret"
    assert auth.verify_password("secret", h)
    assert not auth.verify_password("wrong", h)


def test_token_roundtrip():
    class U:
        id, username, full_name, role = 7, "director", "Директор", "admin"
    token = auth.make_token(U())
    claims = auth.verify(token)
    assert claims["user_id"] == 7 and claims["role"] == "admin"
    assert auth.verify("garbage.token") is None


async def test_first_registration_is_admin_then_closed(session):
    assert await auth.registration_open(session) is True
    token, err = await auth.register(session, "director", "pass1234", "Директор")
    await session.commit()
    assert err is None and token
    assert auth.verify(token)["role"] == "admin"
    # после первого — закрыто
    assert await auth.registration_open(session) is False


async def test_login_success_and_failures(session):
    await auth.register(session, "director", "pass1234", "Директор")
    _, err = await auth.admin_create_user(session, "anna", "pass1234", "Анна", "user")
    await session.commit()
    assert err is None

    token, err = await auth.login(session, "anna", "pass1234")
    assert err is None and auth.verify(token)["username"] == "anna"

    _, err = await auth.login(session, "anna", "wrong")
    assert err is not None

    # деактивированный не входит
    u = await repo.get_user_by_username(session, "anna")
    await repo.set_user_active(session, u.id, False)
    await session.commit()
    _, err = await auth.login(session, "anna", "pass1234")
    assert "деактив" in err.lower()


async def test_validation_and_duplicate(session):
    # короткий логин
    _, err = await auth.register(session, "ab", "pass1234")
    assert "короткий" in err.lower()
    # дубликат логина
    await auth.register(session, "director", "pass1234")
    await session.commit()
    _, err = await auth.admin_create_user(session, "director", "pass1234")
    assert "занят" in err.lower()


async def test_password_policy(session):
    # слишком короткий пароль
    _, err = await auth.register(session, "gooduser", "ab12")
    assert "короткий" in err.lower()
    # достаточной длины, но без цифр — отклоняется
    _, err = await auth.register(session, "gooduser", "onlyletters")
    assert "буквы и цифры" in err.lower()
    # без букв — отклоняется
    _, err = await auth.register(session, "gooduser", "12345678")
    assert "буквы и цифры" in err.lower()
    # валидный пароль проходит
    token, err = await auth.register(session, "gooduser", "pass1234")
    assert err is None and token
