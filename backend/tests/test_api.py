"""Cutover Стадия 3a — тесты REST-эндпоинтов на async (httpx против ASGI)."""


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


async def _register_admin(client, username="director", password="1234"):
    r = await client.post("/api/register",
                          json={"username": username, "password": password, "full_name": "Директор"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


async def test_health(client):
    r = await client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


async def test_registration_bootstrap_then_closed(client):
    assert (await client.get("/api/auth/status")).json()["registration_open"] is True
    token = await _register_admin(client)
    me = await client.get("/api/me", headers=_auth(token))
    assert me.json()["role"] == "admin"
    # регистрация закрыта
    assert (await client.get("/api/auth/status")).json()["registration_open"] is False
    r = await client.post("/api/register", json={"username": "hacker", "password": "1234"})
    assert r.status_code == 403


async def test_login_and_conversations(client):
    await _register_admin(client)
    r = await client.post("/api/login", json={"username": "director", "password": "1234"})
    assert r.status_code == 200
    t = r.json()["token"]

    c = await client.post("/api/conversations", json={"title": "КП XCMG"}, headers=_auth(t))
    cid = c.json()["id"]
    lst = await client.get("/api/conversations", headers=_auth(t))
    assert any(x["id"] == cid for x in lst.json())

    d = await client.delete(f"/api/conversations/{cid}", headers=_auth(t))
    assert d.status_code == 200
    assert (await client.get("/api/conversations", headers=_auth(t))).json() == []


async def test_file_ownership_idor(client):
    admin = await _register_admin(client)
    # админ создаёт сотрудника
    await client.post("/api/admin/users",
                      json={"username": "anna", "password": "1234", "full_name": "Анна", "role": "user"},
                      headers=_auth(admin))
    anna = (await client.post("/api/login", json={"username": "anna", "password": "1234"})).json()["token"]

    # анна загружает файл
    up = await client.post("/api/upload", headers=_auth(anna),
                           files={"file": ("secret.txt", b"hello", "text/plain")})
    fid = up.json()["file_id"]

    # директор (другой пользователь) не может скачать чужой файл — но он admin → можно
    admin_dl = await client.get(f"/api/files/{fid}", params={"token": admin})
    assert admin_dl.status_code == 200

    # заведём второго обычного сотрудника — ему чужой файл недоступен (IDOR → 403)
    await client.post("/api/admin/users",
                      json={"username": "pavel", "password": "1234", "role": "user"},
                      headers=_auth(admin))
    pavel = (await client.post("/api/login", json={"username": "pavel", "password": "1234"})).json()["token"]
    forbidden = await client.get(f"/api/files/{fid}", params={"token": pavel})
    assert forbidden.status_code == 403


async def test_admin_rbac_and_management(client):
    admin = await _register_admin(client)
    await client.post("/api/admin/users",
                      json={"username": "worker", "password": "1234", "full_name": "Работник", "role": "user"},
                      headers=_auth(admin))
    worker = (await client.post("/api/login", json={"username": "worker", "password": "1234"})).json()["token"]

    # сотрудник не имеет доступа к админке
    assert (await client.get("/api/admin/overview", headers=_auth(worker))).status_code == 403

    ov = await client.get("/api/admin/overview", headers=_auth(admin))
    assert ov.status_code == 200 and ov.json()["totals"]["users"] == 2

    users = (await client.get("/api/admin/users", headers=_auth(admin))).json()
    wid = next(u["id"] for u in users if u["username"] == "worker")

    # сброс пароля
    rp = await client.post(f"/api/admin/users/{wid}/password",
                           json={"password": "5678"}, headers=_auth(admin))
    assert rp.status_code == 200
    assert (await client.post("/api/login", json={"username": "worker", "password": "5678"})).status_code == 200

    # деактивация → вход запрещён
    da = await client.post(f"/api/admin/users/{wid}/active",
                           params={"active": "false"}, headers=_auth(admin))
    assert da.status_code == 200
    assert (await client.post("/api/login", json={"username": "worker", "password": "5678"})).status_code == 401


async def test_admin_exports(client):
    admin = await _register_admin(client)
    await client.post("/api/admin/users",
                      json={"username": "anna", "password": "1234", "full_name": "Анна", "role": "user"},
                      headers=_auth(admin))
    users = (await client.get("/api/admin/users", headers=_auth(admin))).json()
    aid = next(u["id"] for u in users if u["username"] == "anna")

    xlsx = await client.get("/api/admin/export/xlsx", headers=_auth(admin))
    assert xlsx.status_code == 200 and len(xlsx.content) > 2000

    docx = await client.get("/api/admin/export/docx", headers=_auth(admin))
    assert docx.status_code == 200 and len(docx.content) > 2000

    user_docx = await client.get(f"/api/admin/users/{aid}/export/docx", headers=_auth(admin))
    assert user_docx.status_code == 200 and len(user_docx.content) > 2000

    # сотруднику экспорт запрещён
    anna = (await client.post("/api/login", json={"username": "anna", "password": "1234"})).json()["token"]
    assert (await client.get("/api/admin/export/xlsx", headers=_auth(anna))).status_code == 403
