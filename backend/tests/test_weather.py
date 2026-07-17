"""Погода (Open-Meteo): форматирование, город не найден, инструмент агента."""
import json

import pytest

import app.orchestrator as orch
from services import weather_svc


def _fetch(found=True):
    def f(url):
        if "geocoding" in url:
            if not found:
                return json.dumps({"results": []})
            return json.dumps({"results": [{"name": "Красноярск", "admin1": "Красноярский край",
                                            "latitude": 56.0, "longitude": 92.8}]})
        return json.dumps({
            "current": {"temperature_2m": 21.3, "apparent_temperature": 23.1,
                        "relative_humidity_2m": 78, "wind_speed_10m": 8.2, "weather_code": 51},
            "daily": {"time": ["2026-07-17", "2026-07-18"],
                      "temperature_2m_max": [24, 25], "temperature_2m_min": [14, 17],
                      "weather_code": [55, 80]}})
    return f


def test_get_weather_formats():
    out = weather_svc.get_weather("Красноярск", fetch=_fetch())
    assert "Красноярск" in out and "21°C" in out
    assert "морось" in out                       # weather_code 51 → слабая морось
    assert "2026-07-17" in out and "14…24°C" in out


def test_get_weather_city_not_found():
    with pytest.raises(weather_svc.WeatherError):
        weather_svc.get_weather("Ннесуществует", fetch=_fetch(found=False))


def test_get_weather_empty_city():
    with pytest.raises(weather_svc.WeatherError):
        weather_svc.get_weather("")


async def test_weather_tool(monkeypatch):
    monkeypatch.setattr(orch.weather_svc, "get_weather", lambda city: f"Погода {city}: ясно")

    async def emit(_e):
        pass
    res = await orch.Orchestrator()._execute_tool(
        "get_weather", {"city": "Москва"}, emit, 1, None, None)
    assert "Москва" in res


async def test_weather_tool_error(monkeypatch):
    def boom(city):
        raise orch.weather_svc.WeatherError("город не найден")
    monkeypatch.setattr(orch.weather_svc, "get_weather", boom)

    async def emit(_e):
        pass
    res = await orch.Orchestrator()._execute_tool(
        "get_weather", {"city": "xxx"}, emit, 1, None, None)
    assert "не удалось" in res.lower()
