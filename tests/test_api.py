from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.routes import get_graph
from main import app


@pytest.fixture
def fake_graph():
    graph = MagicMock()
    app.dependency_overrides[get_graph] = lambda: graph
    yield graph
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_plan_trip_itinerary(client, fake_graph):
    fake_graph.invoke.return_value = {
        "entry": "Rome en juin 2026",
        "final_response": "## Jour 1 — Colisée",
        "source_node": "itinerary",
        "weather": {"avg_temp_max": 29.9, "avg_temp_min": 18.2},
        "budget": "~880€ (estimation)",
        "places": [{"name": "Colisée", "kinds": "historic", "rate": 7}],
    }

    response = client.post("/plan-trip", json={"query": "Rome en juin 2026"})

    assert response.status_code == 200
    fake_graph.invoke.assert_called_once_with("Rome en juin 2026")
    assert response.json() == {
        "itinerary": "## Jour 1 — Colisée",
        "clarification_needed": None,
        "error": None,
        "weather": {"avg_temp_max": 29.9, "avg_temp_min": 18.2},
        "budget": "~880€ (estimation)",
        "places": [{"name": "Colisée", "kinds": "historic", "rate": 7}],
    }


def test_plan_trip_clarification(client, fake_graph):
    fake_graph.invoke.return_value = {
        "entry": "je veux aller à Tokyo",
        "final_response": "Il me manque des informations : les dates ou la durée du séjour.",
        "source_node": "clarification",
        "budget": "unknown",
        "missing_fields": ["les dates ou la durée du séjour"],
    }

    response = client.post("/plan-trip", json={"query": "je veux aller à Tokyo"})

    body = response.json()
    assert response.status_code == 200
    assert body["clarification_needed"].startswith("Il me manque")
    assert body["itinerary"] is None
    assert body["budget"] is None


def test_plan_trip_weather_error(client, fake_graph):
    fake_graph.invoke.return_value = {
        "entry": "voyage à Xyzabcville",
        "final_response": "Je ne trouve pas la destination « Xyzabcville ».",
        "source_node": "weather_error",
        "weather": {"error": "No location data found for 'Xyzabcville'."},
    }

    body = client.post("/plan-trip", json={"query": "voyage à Xyzabcville"}).json()

    assert body["error"].startswith("Je ne trouve pas")
    assert body["weather"] is None
    assert body["itinerary"] is None


def test_plan_trip_rejects_empty_query(client, fake_graph):
    response = client.post("/plan-trip", json={"query": ""})

    assert response.status_code == 422
    fake_graph.invoke.assert_not_called()
