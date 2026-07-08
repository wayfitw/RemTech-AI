"""Issue #18 — единый реестр метаданных инструментов.

Схемы для модели живут в agent/tools.py; здесь — подписи инструментов (статус
в чате и подпись в конструкторе агентов). Раньше эти подписи дублировались в
orchestrator._tool_label и в захардкоженном TOOL_OPTIONS на фронте.
Теперь один источник: orchestrator берёт статус отсюда, фронт — через
GET /api/admin/tools (эндпоинт отдаёт tool_options()).
"""
from agent.tools import TOOLS

# name → (статус в чате, подпись в UI-конструкторе агентов)
TOOL_META: dict[str, tuple[str, str]] = {
    "web_search":            ("🔍 Ищу в интернете...",       "Веб-поиск"),
    "read_url":              ("🌐 Читаю страницу...",         "Читать страницу"),
    "search_knowledge_base": ("📚 Ищу в базе знаний...",      "База знаний"),
    "generate_image":        ("🎨 Рисую...",                  "Генерация картинок"),
    "edit_image":            ("🖼 Редактирую изображение...", "Редактировать картинку"),
    "generate_video":        ("🎬 Генерирую видео...",        "Генерация видео"),
    "create_docx":           ("📝 Создаю документ...",        "Создать Word"),
    "create_pdf":            ("📄 Создаю PDF...",              "Создать PDF"),
    "create_proposal":       ("📑 Готовлю КП...",             "Генератор КП"),
    "read_doc":              ("📖 Читаю документ...",          "Читать документ"),
    "apply_doc_edits":       ("📝 Редактирую документ...",     "Редактировать документ"),
    "fill_template":         ("📋 Заполняю шаблон...",         "Заполнить шаблон"),
}


def status_label(name: str) -> str:
    """Короткая строка статуса в чате при вызове инструмента."""
    meta = TOOL_META.get(name)
    return meta[0] if meta else "⚙️ Делаю..."


def tool_options() -> list[dict]:
    """Инструменты для UI-конструктора агентов: name + подпись, в порядке TOOLS."""
    out = []
    for t in TOOLS:
        name = t.get("name")
        if not name:
            continue
        meta = TOOL_META.get(name)
        out.append({"name": name, "label": meta[1] if meta else name})
    return out
