"""Issue #11 — безопасное расширение файла (защита от инъекции в путь)."""
from app.storage import _safe_ext


def test_safe_ext_normal():
    assert _safe_ext("report.pdf") == "pdf"
    assert _safe_ext("Смета.xlsx") == "xlsx"
    assert _safe_ext("noext") == "bin"


def test_safe_ext_strips_path_injection():
    for name in ("a.docx/../../etc/passwd", "x.p/df", "y.<script>", "z..\\..\\bin"):
        e = _safe_ext(name)
        assert "/" not in e and "\\" not in e and "." not in e and len(e) <= 8
