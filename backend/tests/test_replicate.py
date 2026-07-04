"""Issue #20 — ветки Replicate замоканы и покрыты тестами."""
from services import replicate_svc as rs


class _FileOut:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class _FakeClient:
    def __init__(self, out):
        self._out = out

    def run(self, model, input):
        return self._out


async def test_generate_image_returns_bytes(monkeypatch):
    monkeypatch.setattr(rs, "_client", _FakeClient(_FileOut(b"img-bytes")))
    assert await rs.generate_image_flux("экскаватор") == b"img-bytes"


async def test_edit_image_returns_bytes(monkeypatch):
    monkeypatch.setattr(rs, "_client", _FakeClient(_FileOut(b"edited")))
    assert await rs.edit_image_flux(b"src", "сделай ярче") == b"edited"


async def test_no_client_returns_none(monkeypatch):
    # нет токена Replicate → клиент None → функции возвращают None, не падают
    monkeypatch.setattr(rs, "_client", None)
    assert await rs.generate_image_flux("x") is None
    assert await rs.generate_video("x") is None


def test_read_output_from_url(monkeypatch):
    class _UrlOut:
        url = "http://example/img.jpg"
    import httpx

    class _Resp:
        content = b"downloaded"
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _Resp())
    assert rs._read_output(_UrlOut()) == b"downloaded"
