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
            "read_doc + apply_doc_edits, иначе форматирование будет уничтожено. "
            "НЕ используй для презентаций/слайдов/питча — для них только create_presentation (.pptx). "
            "ПЕРЕД созданием СНАЧАЛА спроси у пользователя стиль: фирменный макет «Ремтехники» "
            "(с бланком RT и реквизитами) или классический (без бланка) — и передай style."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Имя файла без расширения"},
                "content": {
                    "type": "string",
                    "description": "Содержимое: # ## ### для заголовков, ** для жирного, | таблицы | , обычный текст для абзацев",
                },
                "style": {"type": "string", "enum": ["remtekhnika", "classic"],
                          "description": "remtekhnika — фирменный бланк (по умолч.); classic — без бланка. Спроси пользователя."},
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
        "name": "create_presentation",
        "description": (
            "ЕДИНСТВЕННЫЙ инструмент для презентаций — отдаёт файл .pptx (PowerPoint). "
            "ОБЯЗАТЕЛЬНО используй его, а НЕ create_docx/create_pdf, если пользователь просит "
            "«презентацию», «слайды», «питч», «деку», «pptx», «PowerPoint» или «выступление». "
            "Презентация НИКОГДА не должна отдаваться в Word/PDF.\n"
            "Сам продумай структуру и наполни слайды по теме:\n"
            "- Титул (title/subtitle) + 5–9 содержательных слайдов (не 1–2).\n"
            "- Логичный поток: титул → проблема/контекст → решение/предложение → выгоды и "
            "цифры → сроки/этапы → следующие шаги/контакты (адаптируй под тему).\n"
            "- На слайде — короткие ёмкие тезисы (3–6 буллетов), НЕ сплошной абзац; ключевые "
            "числа выделяй **жирным**; заголовок слайда — суть, а не «Слайд 2».\n"
            "- notes — при необходимости заметки докладчика.\n"
            "Иллюстрации (делают презентацию современной — используй их активно):\n"
            "- Реальное фото техники/объекта: image_asset с ключом-моделью (напр. «XCMG XE215», "
            "«LiuGong 856H»). Для КОНКРЕТНОЙ техники/модели предпочитай image_asset — это "
            "настоящее фото, а не рисунок.\n"
            "- AI-иллюстрация: image_prompt — подробное описание на английском для генерации "
            "(для обложки, разделов, концепций, абстрактных тем, где точная модель не нужна). "
            "Обязательно задай cover_image_prompt ИЛИ cover_image_asset для красивой обложки.\n"
            "- Можно указать оба поля у слайда: сначала ищется фото (image_asset), если не "
            "найдено — генерируется по image_prompt. Иллюстрируй большинство слайдов, но не "
            "перегружай (чисто текстовые слайды с цифрами — тоже нормально).\n"
            "- layout: «split» (текст + фото сбоку, по умолчанию) или «full» (фото на весь "
            "слайд с заголовком поверх — для разделов/эффектных акцентов).\n"
            "Данные о компании/технике/ценах бери из базы знаний (search_knowledge_base); "
            "чего нет — не выдумывай, помечай как уточняемое. Готовый файл отправляется пользователю."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Заголовок презентации (титульный слайд)"},
                "subtitle": {"type": "string", "description": "Подзаголовок: для кого / дата / контекст (опционально)"},
                "author": {"type": "string", "description": "Подпись в подвале (по умолчанию «Ремтехника»)"},
                "filename": {"type": "string", "description": "Имя файла без расширения"},
                "cover_image_prompt": {"type": "string", "description": "Промпт (англ.) для AI-обложки; если нужна сгенерированная картинка на титуле"},
                "cover_image_asset": {"type": "string", "description": "Ключ реального фото для обложки (напр. «XCMG экскаватор»)"},
                "slides": {
                    "type": "array",
                    "description": "Слайды по порядку (титул добавляется автоматически из title/subtitle)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Заголовок слайда"},
                            "bullets": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Тезисы слайда (можно **жирным**); коротко, по пунктам",
                            },
                            "image_asset": {"type": "string", "description": "Ключ реального фото техники/объекта (напр. «XCMG XE215»)"},
                            "image_prompt": {"type": "string", "description": "Промпт (англ.) для AI-иллюстрации слайда, если фото не нужно/не найдётся"},
                            "layout": {"type": "string", "enum": ["split", "full"], "description": "split — текст+фото сбоку (по умолч.); full — фото на весь слайд"},
                            "notes": {"type": "string", "description": "Заметки докладчика (опционально)"},
                        },
                        "required": ["title"],
                    },
                },
            },
            "required": ["title", "slides"],
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
        "name": "create_proposal_pptx",
        "description": (
            "Создаёт КП-ПРЕЗЕНТАЦИЮ на технику (.pptx) в фирменном стиле «Ремтехники» — "
            "обложка, слайд «фото + характеристики», доп. слайды (таблица/текст/фото) и "
            "автоматический слайд «цена и условия». Используй, когда просят КП именно как "
            "ПРЕЗЕНТАЦИЮ/слайды на конкретную единицу техники (в отличие от create_proposal — "
            "счётоподобного КП в Word/PDF со списком позиций и наценкой). Характеристики, "
            "цену, гарантию бери из базы знаний (search_knowledge_base) или из документа "
            "поставщика/запроса; чего нет — не выдумывай. Для фото техники укажи image_asset "
            "(ключ реального фото); нет фото — будет аккуратный плейсхолдер."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Имя файла без расширения"},
                "name": {"type": "string", "description": "Модель техники (строка на слайдах), напр. «Экскаватор XCMG XE215C»"},
                "brand": {"type": "string", "description": "Бренд (в шапке справа), напр. XCMG"},
                "client_name": {"type": "string", "description": "Клиент — «Подготовлено для» на обложке"},
                "manager": {"type": "string", "description": "Менеджер (на слайде цены)"},
                "phone": {"type": "string", "description": "Телефон менеджера"},
                "warranty": {"type": "string", "description": "Гарантия, напр. «12 месяцев»"},
                "availability": {"type": "string", "description": "Наличие / срок поставки"},
                "price": {"type": "string", "description": "Стоимость (строкой, с валютой)"},
                "payment_terms": {"type": "array", "items": {"type": "string"}, "description": "Условия оплаты, по пунктам"},
                "trusted_by": {"type": "string", "description": "Строка «Нам доверяют» (опц.; есть дефолт)"},
                "blocks": {
                    "type": "array",
                    "description": "Слайды по порядку (обложку добавь первым блоком type=title; слайд цены добавляется сам)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["title", "split", "table", "photo", "text"],
                                     "description": "title — обложка; split — фото+характеристики; table — таблица; photo — фото; text — текст"},
                            "title": {"type": "string", "description": "Заголовок слайда / модель на обложке"},
                            "text": {"type": "string", "description": "Текст (для title — строка характеристик; для text — абзац)"},
                            "rows": {
                                "type": "array",
                                "description": "Строки для split/table: [параметр, значение]. Для split подзаголовок секции — [\"НАЗВАНИЕ\", null]",
                                "items": {"type": "array", "items": {"type": ["string", "null"]}},
                            },
                            "image_asset": {"type": "string", "description": "Ключ реального фото техники для split/photo (напр. «XCMG XE215»)"},
                        },
                        "required": ["type"],
                    },
                },
            },
            "required": ["name", "blocks"],
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
        "name": "save_tender_profile",
        "description": (
            "Сохраняет профиль поиска тендеров (критерии), чтобы по нему шёл периодический "
            "авто-поиск с уведомлениями и можно было «искать сейчас». Используй, когда просят "
            "«сохрани/запомни такой поиск тендеров». Доступ: закупки/руководство."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Название профиля"},
                "keywords": {"type": "string", "description": "Ключевые слова предмета закупки"},
                "region": {"type": "string", "description": "Регион (опц.)"},
                "budget_min": {"type": "number", "description": "Мин. НМЦК, ₽ (опц.)"},
                "budget_max": {"type": "number", "description": "Макс. НМЦК, ₽ (опц.)"},
                "customer": {"type": "string", "description": "Заказчик, подстрока (опц.)"},
            },
            "required": ["name", "keywords"],
        },
    },
    {
        "name": "list_tender_profiles",
        "description": "Показывает сохранённые профили поиска тендеров (свои; админ — все).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "delete_tender_profile",
        "description": "Удаляет сохранённый профиль поиска тендеров по номеру.",
        "input_schema": {
            "type": "object",
            "properties": {"profile_id": {"type": "integer", "description": "Номер профиля"}},
            "required": ["profile_id"],
        },
    },
    {
        "name": "search_tender_profile",
        "description": (
            "«Искать сейчас» — мгновенный прогон поиска тендеров по сохранённому профилю "
            "(по номеру или названию профиля)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"profile": {"type": "string", "description": "Номер или название профиля"}},
            "required": ["profile"],
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
    {
        "name": "set_reminder",
        "description": (
            "Ставит напоминание. Используй, когда пользователь просит напомнить/не забыть "
            "что-то к определённому времени («напомни завтра в 10 позвонить Диме»). Время "
            "события вычисли САМ по текущей дате/времени (они в системном сообщении) и передай "
            "в datetime как ISO 8601 по местному времени. lead_minutes — за сколько минут до "
            "события слать предупреждения (по умолчанию 60, 30, 10 и 0 = в момент события)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "О чём напомнить, кратко (напр. «позвонить Диме»)"},
                "datetime": {"type": "string",
                             "description": "Дата и время события, ISO 8601 местное, напр. 2026-07-17T10:00"},
                "lead_minutes": {
                    "type": "array", "items": {"type": "integer"},
                    "description": "За сколько минут до события напоминать; 0 = в момент. По умолчанию [60,30,10,0]",
                },
            },
            "required": ["text", "datetime"],
        },
    },
    {
        "name": "list_reminders",
        "description": "Показывает активные напоминания пользователя (с их номерами и временем).",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "cancel_reminder",
        "description": (
            "Отменяет (удаляет) напоминание по его номеру. Номер узнай через list_reminders, "
            "если пользователь не назвал его явно."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {"type": "integer", "description": "Номер напоминания"},
            },
            "required": ["reminder_id"],
        },
    },
    {
        "name": "read_email",
        "description": (
            "Читает последние письма из почты (Gmail или Яндекс) и даёт краткую сводку: "
            "от кого, тема, дата, фрагмент текста. Используй, когда просят проверить почту, "
            "спрашивают «что нового на почте» или просят прочитать письма. Только чтение."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "enum": ["gmail", "yandex"],
                           "description": "Какой ящик читать"},
                "count": {"type": "integer",
                          "description": "Сколько последних писем (по умолчанию 10)", "default": 10},
                "unread_only": {"type": "boolean",
                                "description": "Только непрочитанные", "default": False},
            },
            "required": ["source"],
        },
    },
    {
        "name": "list_tg_chats",
        "description": (
            "Показывает список ТГ-чатов и групп пользователя (имя, тип, id, непрочитанные). "
            "Нужно, чтобы узнать имена/id групп для настройки дайджеста или чтения."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Сколько диалогов (по умолчанию 30)",
                          "default": 30},
            },
            "required": [],
        },
    },
    {
        "name": "read_tg_chat",
        "description": (
            "Читает последние сообщения конкретного ТГ-чата или группы (по @username или id). "
            "Используй, когда просят «что писали в группе X», «прочитай чат с …»."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "@username, id чата/группы или имя"},
                "limit": {"type": "integer", "description": "Сколько сообщений (по умолчанию 30)",
                          "default": 30},
            },
            "required": ["target"],
        },
    },
    {
        "name": "add_digest_group",
        "description": (
            "Добавляет группу в утреннюю авто-сводку по её названию (найдёт среди чатов "
            "пользователя). Используй, когда просят «добавь группу X в утреннюю сводку/дайджест»."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "group": {"type": "string", "description": "Название группы (можно часть)"},
            },
            "required": ["group"],
        },
    },
    {
        "name": "remove_digest_group",
        "description": "Убирает группу из утренней авто-сводки (по названию или номеру).",
        "input_schema": {
            "type": "object",
            "properties": {
                "group": {"type": "string", "description": "Название/часть названия группы"},
            },
            "required": ["group"],
        },
    },
    {
        "name": "list_digest_groups",
        "description": "Показывает группы, включённые в утреннюю авто-сводку.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "analyze_conversation",
        "description": (
            "Анализ переписки или расшифровки звонка. Материал уже в контексте: текст "
            "переписки (пользователь вставил/прислал файлом) или транскрипт аудиозаписи "
            "звонка (аудио распознаётся автоматически при загрузке). ВНИМАТЕЛЬНО разбери "
            "его и вызови инструмент со структурой: договорённости, открытые вопросы, "
            "следующие шаги (кому/что/когда), риски — получишь оформленный отчёт .docx. "
            "Только по содержимому; чего в материале нет — не домысливай."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "О чём переписка/звонок (стороны, тема)"},
                "summary": {"type": "string", "description": "Краткое резюме: суть и общий итог"},
                "agreements": {"type": "array", "items": {"type": "string"},
                               "description": "Достигнутые договорённости"},
                "open_questions": {"type": "array", "items": {"type": "string"},
                                   "description": "Открытые вопросы / что не решено"},
                "next_steps": {"type": "array", "items": {"type": "string"},
                               "description": "Следующие шаги: кому, что, к какому сроку"},
                "risks": {"type": "array", "items": {"type": "string"},
                          "description": "Риски и потенциальные проблемы"},
                "filename": {"type": "string", "description": "Имя файла без расширения"},
            },
            "required": ["summary"],
        },
    },
    {
        "name": "create_contract",
        "description": (
            "Быстро формирует ДОГОВОР (.docx) по краткому запросу («договор поставки на X "
            "для Y»). Порядок: 1) найди подходящий шаблон/условия в базе знаний "
            "(search_knowledge_base по «договор …»); 2) составь текст договора, подставив "
            "известные из запроса и БЗ реквизиты/условия; 3) поля, которых НЕ хватает, "
            "пометь строго как [УТОЧНИТЬ: что именно] — НЕ выдумывай реквизиты, суммы, даты. "
            "Реквизиты «Ремтехники» и правовая оговорка добавляются автоматически. "
            "ПЕРЕД созданием СНАЧАЛА спроси у пользователя стиль: фирменный макет «Ремтехники» "
            "(с бланком) или классический (без бланка) — и передай style. Доступ: продажи/руководство."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filename": {"type": "string", "description": "Имя файла без расширения"},
                "title": {"type": "string", "description": "Заголовок договора"},
                "content": {"type": "string",
                            "description": "Текст договора БЕЗ главного заголовка (он добавляется из "
                                           "title — НЕ дублируй его в тексте). Разделы: # ## для "
                                           "заголовков, ** жирный, | таблицы |. Обычный текст, без "
                                           "HTML-сущностей (&nbsp; и т.п.). Незаполненное — [УТОЧНИТЬ: …]"},
                "style": {"type": "string", "enum": ["remtekhnika", "classic"],
                          "description": "remtekhnika — фирменный бланк (по умолч.); classic — без бланка. Спроси пользователя."},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "ai_news_digest",
        "description": (
            "Публикует дайджест новостей по ИИ. Сначала собери свежие новости (за последние "
            "сутки) через веб-поиск, отбери 5–10 значимых, по каждой — суть ОДНИМ предложением "
            "и ссылку на источник. Не выдумывай и не повторяй одинаковое. Затем вызови "
            "инструмент — он оформит выпуск и опубликует в веб-ленту уведомлений (в Telegram "
            "выпуск придёт твоим текстовым ответом)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Заголовок выпуска (опционально)"},
                "items": {
                    "type": "array",
                    "description": "5–10 новостей",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "Суть новости одним предложением"},
                            "url": {"type": "string", "description": "Ссылка на источник"},
                        },
                        "required": ["text"],
                    },
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "get_weather",
        "description": (
            "Точная погода в городе: текущая + прогноз на 3 дня, из специализированного "
            "источника. ВСЕГДА используй этот инструмент для погоды — НЕ веб-поиск (он даёт "
            "неточные/устаревшие данные). Работает для городов России и мира."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {"type": "string", "description": "Город, напр. «Красноярск»"},
            },
            "required": ["city"],
        },
    },
    {
        "name": "digest_tg_groups",
        "description": (
            "Собирает сообщения из рабочих групп за последние N часов (по умолчанию из "
            "настроенного списка групп) — для краткой сводки «что было в группах за ночь». "
            "После вызова САМ сделай краткую справку по каждой группе: ключевые темы, решения, "
            "вопросы, требующие внимания директора. Не пересказывай всё дословно."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hours": {"type": "integer",
                          "description": "За сколько последних часов (по умолчанию 12 — «за ночь»)",
                          "default": 12},
                "groups": {"type": "array", "items": {"type": "string"},
                           "description": "Конкретные группы (@username/id); пусто — настроенный список"},
            },
            "required": [],
        },
    },
]
