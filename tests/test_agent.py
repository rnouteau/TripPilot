from agent import graph


def _state(**overrides) -> dict:
    state = {
        "entry": "test",
        "city": "Rome",
        "country": "Italie",
        "start_time": "2026-06-10",
        "end_time": "2026-06-12",
        "number_of_days": 3,
        "number_of_travelers": 2,
        "month": "juin",
        "year": 2026,
        "budget": "unknown",
        "places": [],
    }
    state.update(overrides)
    return state


def test_validate_preferences_node_missing_city():
    result = graph.validate_preferences_node(_state(city="unknown"))

    assert result["missing_fields"] == ["la ville de destination"]


def test_validate_preferences_node_missing_dates():
    state = _state(start_time="unknown", end_time="unknown", number_of_days=0, month="unknown", year="unknown")

    result = graph.validate_preferences_node(state)

    assert result["missing_fields"] == ["les dates ou la durée du séjour"]


def test_validate_preferences_node_complete():
    result = graph.validate_preferences_node(_state())

    assert result["missing_fields"] == []
    assert graph.route_after_validation({**_state(), **result}) == "weather"


def test_budget_node_keeps_explicit_budget():
    result = graph.budget_node(_state(budget="1500"))

    assert result == {}


def test_budget_node_estimates_when_unknown():
    places = [{"name": "Colisée"}, {"name": "Panthéon"}, {"error": "Unable to fetch places"}]

    result = graph.budget_node(_state(places=places))

    # 80 €/jour × 3 jours × 2 voyageurs + 15 € × 2 lieux valides × 2 voyageurs
    assert result["budget"].startswith("~540€")
    assert "2 activités" in result["budget"]


def test_weather_node_handles_error_gracefully(mocker):
    mock_get_weather = mocker.patch.object(
        graph, "get_weather", return_value={"error": "No location data found for 'Xyzabcville'."}
    )

    result = graph.weather_node(_state(city="Xyzabcville"))

    mock_get_weather.assert_called_once()
    assert result["weather"] == {"error": "No location data found for 'Xyzabcville'."}
    assert result["latitude"] is None
    assert result["longitude"] is None
    assert graph.route_after_weather({**_state(), **result}) == "weather_error"
