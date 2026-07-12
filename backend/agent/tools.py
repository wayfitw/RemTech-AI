"""Схемы инструментов для Claude (Function Calling). Этап 1 — базовый набор
веб-оболочки mybot. Портировано из mybot/agent/tools.py (подмножество)."""

TOOLS = [
    # Серверный веб-поиск Anthropic — выполняется на их стороне, обработчик не нужен.
    {
        "type": "web_search_20250305",
        "name": "web_search",
        "max_uses": 5,
    },
    {
        "name": "read_url",
        "description": (
            "Читает содержимое веб-страницы по ссылке и извлекает текст. "
            "Используй когда пользователь присылает URL или когда после поиска "
            "нужно прочитать конкретную страницу."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Ссылка на страницу"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "search_knowledge_base",
        "description": (
            "Ищет ответ в базе знаний компании «Ремтехника» (регламенты, прайсы, "
            "каталоги XCMG, шаблоны, история). ВСЕГДА используй при вопросах по технике, "
            "запчастям, ценам, условиям и внутренним документам — прежде чем отвечать. "
            "Возвращает релевантные фрагменты со ссылкой на документ-источник."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос по сути вопроса"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "generate_image",
        "description": (
            "Генерирует изображение по текстовому описанию (FLUX Kontext Pro). "
            "Используй когда просят нарисовать, сгенерировать или создать картинку. "
            "Сначала переведи описание в детальный английский промпт."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Детальное описание на английском"},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "edit_image",
        "description": (
            "Редактирует последнее загруженное/сгенерированное изображение точечно — "
            "меняет только указанную область, остальное сохраняется. "
            "Instruction MUST be in English and specific: describe what to ADD/REMOVE/CHANGE "
            "AND explicitly say 'keep everything else exactly the same'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "instruction": {"type": "string", "description": "English prompt: что изменить и что сохранить"},
            },
            "required": ["instruction"],
        },
    },
    {
        "name": "generate_video",
        "description": (
            "Генерирует видео. Если есть загруженное/сгенерированное фото — оживляет его "
            "(image-to-video), иначе создаёт с нуля. Занимает 2-5 минут."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Описание видео на английском"},
                "duration": {"type": "integer", "description": "Длина в секундах (5 или 10)", "default": 5},
            },
            "required": ["prompt"],
        },
    },
    {
        "name": "create_docx",
        "description": (
            "Создаёт Word-документ (.docx) с нуля. ТОЛЬКО когда пользователь просит создать "
            "НОВЫЙ документ и НЕ загружал .docx. Если .docx уже загружен — используй "
            "read_doc + apply_doc_edits, иначе форматирование будет уничтожено."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Имя файла без расширения"},
                "content": {
                    "type": "string",
                    "description": "Содержимое: # ## ### для заголовков, ** для жирного, | таблицы | , обычный текст для абзацев",
                },
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "create_pdf",
        "description": (
            "Создаёт PDF-документ из текста (заголовки # ## ###, **жирный**). "
            "Используй когда пользователь явно просит PDF, а не Word."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Имя файла без расширения"},
                "content": {"type": "string", "description": "Содержимое документа"},
            },
            "required": ["filename", "content"],
        },
    },
    {
        "name": "create_proposal",
        "description": (
            "Создаёт коммерческое предложение (КП) в фирменном стиле «Ремтехники» (Word): "
            "таблица позиций, наценка, итог, условия и контакты. Используй когда просят "
            "составить/сделать КП или коммерческое предложение. Цены и позиции бери из базы "
            "знаний (search_knowledge_base) или у пользователя; наценку — из запроса."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Имя файла без расширения"},
                "title": {"type": "string", "description": "Заголовок КП (на что предложение)"},
                "client": {"type": "string", "description": "Кому — клиент/организация"},
                "items": {
                    "type": "array",
                    "description": "Позиции предложения",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Наименование позиции"},
                            "qty": {"type": "number", "description": "Количество", "default": 1},
                            "price": {"type": "number", "description": "Базовая цена за единицу, ₽"},
                        },
                        "required": ["name", "price"],
                    },
                },
                "markup_percent": {"type": "number", "description": "Наценка в процентах", "default": 0},
                "contact": {"type": "string", "description": "Контакт для связи"},
                "validity_days": {"type": "integer", "description": "Срок действия (рабочих дней)", "default": 14},
                "notes": {"type": "string", "description": "Примечания/условия"},
                "format": {"type": "string", "enum": ["docx", "pdf", "both"],
                           "description": "Формат КП: docx (по умолчанию), pdf или both", "default": "docx"},
            },
            "required": ["filename", "items"],
        },
    },
    {
        "name": "read_doc",
        "description": (
            "Читает структуру загруженного Word-документа (.docx) и возвращает список "
            "параграфов с hash-ID. ВСЕГДА вызывай ПЕРЕД apply_doc_edits. "
            "Формат: 'P9#f3c1 | Текст параграфа...'"
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "apply_doc_edits",
        "description": (
            "Редактирует загруженный Word-документ по hash-ID параграфов (ref из read_doc), "
            "сохраняя форматирование. Сначала read_doc, потом apply_doc_edits.\n"
            "Операции: rewrite (ref + new_text), delete (ref), insert_after (ref + text)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "operations": {
                    "type": "array",
                    "description": "Список правок",
                    "items": {
                        "type": "object",
                        "properties": {
                            "op": {"type": "string", "enum": ["rewrite", "delete", "insert_after"]},
                            "ref": {"type": "string", "description": "Hash-ref параграфа, напр. 'P9#f3c1'"},
                            "new_text": {"type": "string", "description": "Для rewrite"},
                            "text": {"type": "string", "description": "Для insert_after"},
                        },
                        "required": ["op", "ref"],
                    },
                },
                "filename": {"type": "string", "description": "Имя выходного файла без расширения"},
            },
            "required": ["operations"],
        },
    },
    {
        "name": "analyze_spec",
        "description": (
            "Формирует отчёт анализа технического задания (ТЗ) в Word. Используй когда "
            "пользователь загрузил ТЗ и просит его проанализировать. Сначала ВНИМАТЕЛЬНО "
            "разбери текст ТЗ (он в контексте), выдели требования, риски, противоречия и "
            "пробелы (чего не хватает), затем вызови analyze_spec со структурированными "
            "findings — получишь оформленный отчёт. Ответ и findings — на русском."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Название/предмет ТЗ"},
                "summary": {"type": "string", "description": "Краткое резюме: о чём ТЗ и общий вывод"},
                "requirements": {"type": "array", "items": {"type": "string"},
                                 "description": "Список выявленных требований"},
                "risks": {"type": "array", "items": {"type": "string"},
                          "description": "Риски и потенциальные проблемы"},
                "contradictions": {"type": "array", "items": {"type": "string"},
                                   "description": "Противоречия в ТЗ"},
                "gaps": {"type": "array", "items": {"type": "string"},
                         "description": "Пробелы — чего не хватает/что уточнить"},
                "filename": {"type": "string", "description": "Имя файла без расширения"},
            },
            "required": ["summary"],
        },
    },
    {
        "name": "create_estimate",
        "description": (
            "Создаёт смету/бюджет в Excel (.xlsx) с позициями, настоящими формулами "
            "(суммы и итог считаются в Excel) и фирменным оформлением. Используй когда "
            "просят составить смету, расчёт стоимости или бюджет в таблице."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Имя файла без расширения"},
                "title": {"type": "string", "description": "Название сметы"},
                "client": {"type": "string", "description": "Заказчик (опционально)"},
                "markup_percent": {"type": "number", "description": "Наценка в процентах", "default": 0},
                "notes": {"type": "string", "description": "Примечания (опционально)"},
                "items": {
                    "type": "array",
                    "description": "Позиции сметы",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Наименование"},
                            "unit": {"type": "string", "description": "Единица измерения, напр. шт/м/ч"},
                            "qty": {"type": "number", "description": "Количество", "default": 1},
                            "price": {"type": "number", "description": "Цена за единицу, ₽"},
                        },
                        "required": ["name", "price"],
                    },
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "search_tenders",
        "description": (
            "Ищет закупки/тендеры на ЕИС zakupki.gov.ru (44-ФЗ/223-ФЗ) по ключевым "
            "словам, региону, диапазону бюджета (НМЦК) и заказчику. Используй когда "
            "просят найти тендеры/закупки/конкурсы. Возвращает список: номер, "
            "наименование, заказчик, НМЦК, срок подачи, ссылка. Данные из внешнего "
            "источника — если ничего не найдено или источник недоступен, скажи честно, "
            "не придумывай закупки."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "keywords": {"type": "string",
                             "description": "Ключевые слова предмета закупки, напр. 'экскаватор XCMG'"},
                "region": {"type": "string", "description": "Регион (по названию), опционально"},
                "budget_min": {"type": "number", "description": "Минимальная НМЦК, ₽, опционально"},
                "budget_max": {"type": "number", "description": "Максимальная НМЦК, ₽, опционально"},
                "customer": {"type": "string", "description": "Заказчик (подстрока), опционально"},
            },
            "required": ["keywords"],
        },
    },
    {
        "name": "analyze_procurement",
        "description": (
            "Предварительный анализ закупки: извлекает из карточки/извещения ЕИС предмет, "
            "заказчика, НМЦК, срок подачи и требования к участникам. Передай ссылку на "
            "закупку (из search_tenders) ИЛИ текст карточки. ПОСЛЕ вызова: сверь требования "
            "с профилем компании «Ремтехника» через search_knowledge_base и дай честный "
            "вердикт соответствия (подходит/не подходит/нужно уточнить) со ссылками на "
            "источники требований. Если данных в карточке не хватает — прямо скажи, чего "
            "именно, и не домысливай."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "link": {"type": "string", "description": "Ссылка на извещение закупки (ЕИС)"},
                "card_text": {"type": "string",
                              "description": "Текст карточки закупки, если ссылки нет"},
            },
            "required": [],
        },
    },
    {
        "name": "fill_template",
        "description": (
            "Заполняет загруженный .docx-шаблон: подставляет значения в поля вида "
            "{{ПОЛЕ}}, сохраняя форматирование. Используй когда пользователь прислал "
            "шаблон (договор/КП/заявку) с плейсхолдерами и просит заполнить его данными. "
            "Сначала пользователь загружает .docx-шаблон, затем ты вызываешь fill_template."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fields": {
                    "type": "array",
                    "description": "Пары поле→значение для подстановки",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string", "description": "Имя поля без скобок, напр. КЛИЕНТ"},
                            "value": {"type": "string", "description": "Значение для подстановки"},
                        },
                        "required": ["name", "value"],
                    },
                },
                "filename": {"type": "string", "description": "Имя выходного файла без расширения"},
            },
            "required": ["fields"],
        },
    },
]
