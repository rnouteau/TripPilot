import calendar
from unittest.mock import MagicMock

import pytest

from tools import places, weather


def _mock_response(payload: dict) -> MagicMock:
    response = MagicMock()
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


def _daily(dates: list[str], temp_max: list[float], temp_min: list[float], precip: list[float]) -> dict:
    return {
        "daily": {
            "time": dates,
            "temperature_2m_max": temp_max,
            "temperature_2m_min": temp_min,
            "precipitation_sum": precip,
        }
    }


def test_get_coordinates_success(monkeypatch):
    payload = {
        "results": [
            {"name": "Lisbonne", "country": "Belgique", "latitude": 49.94, "longitude": 4.42},
            {"name": "Lisbonne", "country": "Portugal", "latitude": 38.72, "longitude": -9.15, "population": 517802},
        ]
    }
    mock_get = MagicMock(return_value=_mock_response(payload))
    monkeypatch.setattr(weather.requests, "get", mock_get)

    latitude, longitude, name = weather.get_coordinates("Lisbonne", "Portugal")

    assert (latitude, longitude) == (38.72, -9.15)
    assert name == "Lisbonne, Portugal"
    assert mock_get.call_args.kwargs["params"]["name"] == "Lisbonne"


def test_get_coordinates_city_not_found(monkeypatch):
    monkeypatch.setattr(weather.requests, "get", MagicMock(return_value=_mock_response({})))

    with pytest.raises(ValueError, match="No location data found"):
        weather.get_coordinates("Xyzabcville")


def test_get_weather_precise_dates(monkeypatch):
    monkeypatch.setattr(weather, "get_coordinates", lambda query, country=None: (41.9, 12.5, "Rome, Italie"))
    fetched_periods = []

    def fake_fetch_archive(latitude, longitude, start, end):
        fetched_periods.append((start, end))
        return _daily([start, end], [30.0, 28.0], [18.0, 16.0], [0.0, 2.0])

    monkeypatch.setattr(weather, "_fetch_archive", fake_fetch_archive)

    result = weather.get_weather(
        city="Rome", country="Italie",
        start_time="2026-06-10", end_time="2026-06-11",
        date_precise=True, month="juin", year=2026, number_of_days=2,
    )

    assert result["start_time"] == "2026-06-10"
    assert result["end_time"] == "2026-06-11"
    assert result["number_of_days"] == 2
    assert result["weather"] == {
        "avg_temp_max": 29.0,
        "avg_temp_min": 17.0,
        "avg_precipitation_mm": 1.0,
        "years_used": weather.ARCHIVE_YEARS_BACK,
    }
    assert fetched_periods[0] == ("2025-06-10", "2025-06-11")
    assert len(fetched_periods) == weather.ARCHIVE_YEARS_BACK


def test_get_weather_month_only(monkeypatch):
    monkeypatch.setattr(weather, "get_coordinates", lambda query, country=None: (38.7, -9.1, "Lisbonne, Portugal"))
    requested_months = []

    def fake_fetch_month_archive(latitude, longitude, year, month):
        requested_months.append((year, month))
        last_day = calendar.monthrange(year, month)[1]
        dates = [f"{year}-{month:02d}-{d:02d}" for d in range(1, last_day + 1)]
        return _daily(dates, [22.0] * last_day, [14.0] * last_day, [0.0] * last_day)

    monkeypatch.setattr(weather, "_fetch_month_archive", fake_fetch_month_archive)

    result = weather.get_weather(
        city="Lisbonne", country="Portugal",
        start_time="unknown", end_time="unknown",
        date_precise=False, month="mai", year=2026, number_of_days=5,
    )

    assert all(month == 5 for _, month in requested_months)
    assert result["number_of_days"] == 5
    assert result["start_time"].startswith("2026-05-")
    assert result["weather"]["avg_temp_max"] == 22.0
    assert result["latitude"] == 38.7
    assert result["resolved_location"] == "Lisbonne, Portugal"


def test_find_best_period_selects_best_window(monkeypatch):
    sunny_days = {10, 11, 12}

    def fake_fetch_month_archive(latitude, longitude, year, month):
        last_day = calendar.monthrange(year, month)[1]
        days = range(1, last_day + 1)
        return _daily(
            [f"{year}-{month:02d}-{d:02d}" for d in days],
            [30.0 if d in sunny_days else 15.0 for d in days],
            [20.0 if d in sunny_days else 8.0 for d in days],
            [0.0 if d in sunny_days else 10.0 for d in days],
        )

    monkeypatch.setattr(weather, "_fetch_month_archive", fake_fetch_month_archive)

    result = weather.find_best_period(48.85, 2.35, target_year=2026, target_month=6, duration_days=3)

    assert result["start_time"] == "2026-06-10"
    assert result["end_time"] == "2026-06-12"
    assert result["weather"]["avg_temp_max"] == 30.0
    assert result["weather"]["avg_precipitation_mm"] == 0.0


def test_get_places_with_kinds_filter(monkeypatch):
    payload = {
        "features": [
            {"properties": {"name": "Musée du Louvre", "kinds": "museums,cultural", "rate": 7}},
        ]
    }
    mock_get = MagicMock(return_value=_mock_response(payload))
    monkeypatch.setattr(places.requests, "get", mock_get)

    result = places.get_places("Paris", 48.85, 2.35, limit=5, kinds=["museums", "historic"])

    params = mock_get.call_args.kwargs["params"]
    assert params["kinds"] == "museums,historic"
    assert params["limit"] == 5
    assert result == [{"name": "Musée du Louvre", "kinds": "museums,cultural", "rate": 7}]
