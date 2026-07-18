"""#45 Этап 3 — REST КП-презентаций: RBAC, безопасность фото (owner-only),
генерация + скачивание, извлечение (модель замокана)."""
import io

from PIL import Image

from services import docgen, proposal_pptx


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _png():
    b = io.BytesIO()
    Image.new("RGB", (80, 60), (200, 160, 40)).save(b, "PNG")
    return b.getvalue()


async def _register_admin(client):
    r = await client.post("/api/register",
                          json={"username": "director", "password": "pass1234", "full_name": "Дир"})
    return r.json()["token"]


async def _make_user(client, admin, username, role):
    await client.post("/api/admin/users",
                      json={"username": username, "password": "pass1234", "full_name": username, "role": role},
                      headers=_auth(admin))
    return (await client.post("/api/login",
                              json={"username": username, "password": "pass1234"})).json()["token"]


async def test_proposals_rbac(client):
    admin = await _register_admin(client)
    worker = await _make_user(client, admin, "worker", "user")   # не продажи/руководство
    r = await client.post("/api/proposals/photo",
                          files={"file": ("p.png", _png(), "image/png")}, headers=_auth(worker))
    assert r.status_code == 403                                  # роль не допущена
    # полностью без авторизации (чистим cookie сессии, оставленный логином) → 401
    client.cookies.clear()
    assert (await client.post("/api/proposals/generate",
                              json={"name": "X", "blocks": []})).status_code == 401


async def test_proposals_photo_generate_download(client):
    admin = await _register_admin(client)                        # admin проходит RBAC
    up = await client.post("/api/proposals/photo",
                           files={"file": ("exc.png", _png(), "image/png")}, headers=_auth(admin))
    assert up.status_code == 200
    img_id = up.json()["image_id"]
    payload = {"name": "Экскаватор XCMG", "filename": "КП_XE215",
               "blocks": [{"type": "title", "title": "Экскаватор XCMG"},
                          {"type": "split", "image_id": img_id, "rows": [["Мощность", "118 кВт"]]}]}
    gen = await client.post("/api/proposals/generate", json=payload, headers=_auth(admin))
    assert gen.status_code == 200, gen.text
    fid = gen.json()["file_id"]
    dl = await client.get(f"/api/files/{fid}", headers=_auth(admin))
    assert dl.status_code == 200 and dl.content[:2] == b"PK"
    from pptx import Presentation
    prs = Presentation(io.BytesIO(dl.content))
    pics = sum(1 for s in prs.slides for sh in s.shapes if sh.shape_type == 13)
    assert pics == 1                                             # фото владельца встроено


async def test_proposals_photo_owner_only(client):
    # чужой image_id → 403 (белый список = только собственные файлы, критерий безопасности)
    admin = await _register_admin(client)
    sales = await _make_user(client, admin, "seller", "продажи")
    up = await client.post("/api/proposals/photo",
                           files={"file": ("a.png", _png(), "image/png")}, headers=_auth(admin))
    other_id = up.json()["image_id"]                            # файл принадлежит admin
    payload = {"name": "X", "blocks": [{"type": "split", "image_id": other_id, "rows": [["a", "b"]]}]}
    r = await client.post("/api/proposals/generate", json=payload, headers=_auth(sales))
    assert r.status_code == 403                                  # продажник не возьмёт чужое фото


async def test_proposals_extract(client, monkeypatch):
    admin = await _register_admin(client)

    async def fake_extract(data, filename, db, **kw):
        return {"name": "Погрузчик LiuGong CLG856H", "brand": "LiuGong",
                "blocks": [{"type": "title", "title": "Погрузчик LiuGong CLG856H"}]}

    monkeypatch.setattr(proposal_pptx, "extract_slides_from_document", fake_extract)
    docx = docgen.create_docx("Погрузчик LiuGong CLG856H. Цена 12 400 000 руб.", "kp")
    r = await client.post(
        "/api/proposals/extract",
        files={"file": ("kp.docx", docx,
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        headers=_auth(admin))
    assert r.status_code == 200, r.text
    assert r.json()["brand"] == "LiuGong" and r.json()["blocks"][0]["type"] == "title"
