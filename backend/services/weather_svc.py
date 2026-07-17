"""Точная погода через Open-Meteo (без API-ключа; города РФ и мира).

Веб-поиск даёт неточную/устаревшую погоду — здесь берём данные из специализированного
источника: геокодирование названия города → прогноз по координатам. Сетевой доступ —
через SSRF-контур websearch.fetch_raw (#8). Город не найден/источник недоступен →
понятный WeatherError.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode

from services import websearch

_GEO = "https://geocoding-api.open-meteo.com/v1/search"
_FORECAST = "https://api.open-meteo.com/v1/forecast"

# Коды погоды WMO → описание по-русски.
_WMO = {
    0: "ясно", 1: "в основном ясно", 2: "переменная облачность", 3: "пасмурно",
    45: "туман", 48: "изморозь", 51: "слабая морось", 53: "морось", 55: "сильная морось",
    56: "ледяная морось", 57: "сильная ледяная морось",
    61: "небольшой дождь", 63: "дождь", 65: "сильный дождь",
    66: "ледяной дождь", 67: "сильный ледяной дождь",
    71: "небольшой снег", 73: "снег", 75: "сильный снег", 77: "снежная крупа",
    80: "небольшой ливень", 81: "ливень", 82: "сильный ливень",
    85: "снегопад", 86: "сильный снегопад",
    95: "гроза", 96: "гроза с градом", 99: "сильная гроза с градом",
}


class WeatherError(Exception):
    """Не удалось получить погоду (город не найден/источник недоступен)."""


def _desc(code) -> str:
    try:
        return _WMO.get(int(code), f"код {code}")
    except (TypeError, ValueError):
        return "н/д"


def _geocode(city: str, fetch) -> dict:
    try:
        data = json.loads(fetch(f"{_GEO}?{urlencode({'name': city, 'count': 1, 'language': 'ru'})}"))
    except Exception as e:
        raise WeatherError(f"источник погоды недоступен: {type(e).__name__}") from e
    res = data.get("results") or []
    if not res:
        raise WeatherError(f"город «{city}» не найден")
    return res[0]


def get_weather(city: str, *, fetch=websearch.fetch_raw) -> str:
    """Текущая погода + прогноз на 3 дня для города. fetch подменяется в тестах."""
    city = (city or "").strip()
    if not city:
        raise WeatherError("не указан город")
    g = _geocode(city, fetch)
    name = g["name"] + (f", {g['admin1']}" if g.get("admin1") else "")
    q = urlencode({
        "latitude": g["latitude"], "longitude": g["longitude"],
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "timezone": "auto", "forecast_days": 3,
    })
    try:
        fc = json.loads(fetch(f"{_FORECAST}?{q}"))
    except Exception as e:
        raise WeatherError(f"источник погоды недоступен: {type(e).__name__}") from e

    cur = fc.get("current") or {}
    lines = [
        f"Погода — {name}:",
        f"Сейчас: {round(cur.get('temperature_2m', 0))}°C "
        f"(ощущается {round(cur.get('apparent_temperature', 0))}°C), {_desc(cur.get('weather_code'))}, "
        f"влажность {cur.get('relative_humidity_2m', '?')}%, ветер {round(cur.get('wind_speed_10m', 0))} км/ч.",
    ]
    daily = fc.get("daily") or {}
    days = daily.get("time") or []
    for i in range(min(3, len(days))):
        lines.append(
            f"{days[i]}: {round(daily['temperature_2m_min'][i])}…{round(daily['temperature_2m_max'][i])}°C, "
            f"{_desc(daily['weather_code'][i])}")
    return "\n".join(lines)
