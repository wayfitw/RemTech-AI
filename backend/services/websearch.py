"""Чтение веб-страниц (read_url). Веб-поиск выполняется на стороне Anthropic
(серверный инструмент web_search), поэтому отдельного обработчика не требует."""


def read_url(url: str) -> str:
    import trafilatura

    downloaded = trafilatura.fetch_url(url)
    if not downloaded:
        return "Не удалось загрузить страницу."
    text = trafilatura.extract(downloaded, include_comments=False, include_tables=True)
    if not text:
        return "Не удалось извлечь текст со страницы."
    return text[:8000]
