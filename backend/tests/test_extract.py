"""Issue #7 — тест защиты от decompression-bomb в извлечении текста."""
import io
import zipfile

import pytest

from services.extract import DecompressionBomb, _guard_zip, extract_text


def _bomb_zip() -> bytes:
    """Zip с одним сильно сжимаемым (нулевым) файлом — высокий коэффициент сжатия."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("payload.bin", b"\x00" * 10_000_000)   # 10 МБ нулей → сожмётся в килобайты
    return buf.getvalue()


def _small_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a.txt", b"hello world")
    return buf.getvalue()


def test_guard_rejects_bomb():
    with pytest.raises(DecompressionBomb):
        _guard_zip(_bomb_zip())


def test_guard_allows_small_zip():
    _guard_zip(_small_zip())   # не должно бросать


def test_guard_ignores_non_zip():
    _guard_zip(b"not a zip at all")   # пропускаем — не zip


def test_extract_docx_bomb_is_contained():
    # extract_text ловит исключение и возвращает сообщение, а не разворачивает бомбу
    out = extract_text(_bomb_zip(), "payload.docx")
    assert "Не удалось извлечь" in out


def test_extract_respects_max_chars():
    # аудит БЗ: длинные документы не должны обрезаться дефолтным лимитом при ингесте
    big = ("абвгд " * 10_000).encode()   # ~60k символов
    assert len(extract_text(big, "doc.txt")) == 20_000            # дефолт для чата
    assert len(extract_text(big, "doc.txt", max_chars=200_000)) == len(big.decode())  # для БЗ — целиком
