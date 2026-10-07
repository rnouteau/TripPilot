from datetime import date, timedelta
from typing import Optional

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from config import AVG_ACTIVITY_COST, DAILY_COST_PER_PERSON, OLLAMA_MODEL
from tools import get_places, get_weather

from .cache import cached_llm_call
from .prompts import (
    EXTRACT_PREFERENCES_SYSTEM,
    ITINERARY_SYSTEM,
    MATCH_DESIRES_SYSTEM,
    OPENTRIPMAP_KINDS,
    build_extract_preferences_prompt,
    build_itinerary_prompt,
    build_match_desires_prompt,
)
from .state import DesiresMatch, StateDict


class ItineraryOutput(BaseModel):
    itinerary: str


class TravelPreferences(BaseModel):
    ville: Optional[str] = None
    pays: Optional[str] = None
    date_debut: Optional[str] = None
    date_fin: Optional[str] = None
    date_precise: Optional[bool] = None  # True si l'utilisateur a donné un jour exact, False si seulement un mois/période vague
    nombre_de_jours: Optional[int] = None
    nombre_de_voyageurs: Optional[int] = None
    budget: Optional[str] = None  # Placeholder for budget estimation
    envies: Optional[list[str]] = None  # Placeholder for user desires/preferences
    mois_vise: Optional[str] = None  # ex: "juin", même si pas de date précise
    annee_visee: Optional[int] = None
    
    
def _parse_iso(value: Optional[str]) -> Optional[date]:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None
    
def extract_preferences_node(state: StateDict) -> dict:
    print("Extract preferences node reached")
    today = date.today()
    next_monday = today + timedelta(days=7 - today.weekday())

    schema = TravelPreferences.model_json_schema()
    schema["required"] = list(schema["properties"].keys())  # all fields are required in the output       
    response = cached_llm_call(
        model=OLLAMA_MODEL,
        system_prompt=EXTRACT_PREFERENCES_SYSTEM,
        user_prompt=build_extract_preferences_prompt(state, today, next_monday),
        response_schema=schema,
    )
    prefs = TravelPreferences.model_validate(response)

    start = _parse_iso(prefs.date_debut)
    end = _parse_iso(prefs.date_fin)
    days = prefs.nombre_de_jours

    if start and end:
        days = (end - start).days + 1
    elif start and days:
        end = start + timedelta(days=days - 1)

    travelers = prefs.nombre_de_voyageurs or 1  # défaut : 1 voyageur

    return {
        "city": prefs.ville or "unknown",
        "country": prefs.pays or "unknown",
        "start_time": start.isoformat() if start else "unknown",
        "end_time": end.isoformat() if end else "unknown",
        "number_of_days": days or 0,
        "number_of_travelers": travelers,
        "month": prefs.mois_vise or "unknown",
        "year": prefs.annee_visee or "unknown",
        "budget": prefs.budget or "unknown",  # Placeholder for budget estimation
        "desires": prefs.envies or None,  # Placeholder for user desires/preferences
    }

def validate_preferences_node(state: StateDict) -> dict:
    """
    Checks which essential fields are missing after extraction.
    """
    print("Validate preferences node reached")
    missing = []

    if state["city"] == "unknown":
        missing.append("la ville de destination")

    has_precise_dates = state["start_time"] != "unknown" and state["number_of_days"] != 0
    has_month_only = state["month"] != "unknown" and state["year"] != "unknown"

    if not has_precise_dates and not has_month_only:
        missing.append("les dates ou la durée du séjour")

    return {"missing_fields": missing}


def route_after_validation(state: StateDict) -> str:
    """
    Decides whether to continue the pipeline or ask for clarification.
    """
    if state["missing_fields"]:
        return "clarification"
    return "weather"


def clarification_node(state: StateDict) -> dict:
    """
    Terminal node reached when essential info is missing.
    """
    print("Clarification node reached")
    missing_str = ", ".join(state["missing_fields"])
    message = (
        f"Il me manque des informations pour préparer ton voyage : {missing_str}. "
        "Peux-tu préciser ?"
    )

    return {"final_response": message, "source_node": "clarification"}

def weather_node(state: StateDict) -> StateDict:
    print("Weather node reached")

    weather_info = get_weather(
        city=state["city"],
        country=state["country"],
        start_time=state["start_time"],
        end_time=state["end_time"],
        date_precise=state["start_time"] != "unknown" and state["number_of_days"] != 0,
        month=state["month"],
        year=state["year"],
        number_of_days=state["number_of_days"],
    )

    if "error" in weather_info:
        return {
            "weather": {"error": weather_info["error"]},
            "latitude": weather_info.get("latitude"),
            "longitude": weather_info.get("longitude"),
        }

    return {
        "start_time": weather_info["start_time"],
        "end_time": weather_info["end_time"],
        "number_of_days": weather_info["number_of_days"],
        "latitude": weather_info["latitude"],
        "longitude": weather_info["longitude"],
        "weather": weather_info["weather"],
    }


def route_after_weather(state: StateDict) -> str:
    if (state.get("weather") or {}).get("error"):
        return "weather_error"
    return "places"


def weather_error_node(state: StateDict) -> dict:
    print("Weather error node reached")
    error = state["weather"]["error"]
    destination = state["city"] if state["city"] != "unknown" else state["country"]

    if error.startswith("No location data found"):
        message = (
            f"Je ne trouve pas la destination « {destination} ». "
            "Vérifie l'orthographe ou précise le pays (ex : « Porto, Portugal »)."
        )
    elif error.startswith("Unable to fetch location data"):
        message = (
            "Le service de géolocalisation est momentanément indisponible. "
            "Réessaie dans quelques instants."
        )
    elif error.startswith("No historical data"):
        message = (
            f"Je n'ai pas pu récupérer de données météo pour {destination} "
            "sur cette période. Réessaie plus tard ou choisis d'autres dates."
        )
    else:
        message = f"Impossible de préparer ton voyage pour le moment : {error}"

    return {"final_response": message, "source_node": "weather_error"}


def budget_node(state: StateDict) -> dict:
    print("Budget node reached")
    if state["budget"] != "unknown":
        # L'utilisateur a donné un budget explicite, on ne l'écrase pas
        return {}

    daily_rate = DAILY_COST_PER_PERSON.get(state["country"], DAILY_COST_PER_PERSON["default"])
    days = state["number_of_days"] or 1
    travelers = state["number_of_travelers"] or 1

    places = state.get("places", [])
    nb_places = len([p for p in places if "error" not in p])

    lodging_and_food = daily_rate * days * travelers
    activities = AVG_ACTIVITY_COST * nb_places * travelers

    estimated_budget = lodging_and_food + activities
    print(f"Estimated budget for {travelers} travelers over {days} days with {nb_places} activities: {estimated_budget}€")
    return {
        "budget": f"~{estimated_budget}€ (estimation : hébergement/repas + {nb_places} activités)"
    }


def match_desires_to_kinds(desires: list[str]) -> list[str]:
    """
    Maps free-text travel desires to a list of valid OpenTripMap kinds.
    Falls back to an empty list (no filtering) if the LLM returns garbage.
    """
    if not desires:
        return []

    schema = DesiresMatch.model_json_schema()
    schema["required"] = list(schema["properties"].keys())

    response = cached_llm_call(
        model=OLLAMA_MODEL,
        system_prompt=MATCH_DESIRES_SYSTEM,
        user_prompt=build_match_desires_prompt(desires),
        response_schema=schema,
    )

    match = DesiresMatch.model_validate(response)
    # sécurité : on ne garde que les tags réellement valides, au cas où le modèle en invente
    valid_kinds = [k for k in match.kinds if k in OPENTRIPMAP_KINDS]
    return valid_kinds

def places_node(state: StateDict) -> StateDict:
    print("Places node reached")

    latitude, longitude = state.get("latitude"), state.get("longitude")
    if latitude is None or longitude is None:
        return {"places": [], "number_of_activities": 0, "matched_kinds": []}

    city = state["city"]
    limited_activities = max(state["number_of_days"] * 2, 4)

    desires = state.get("desires") or []
    kinds = match_desires_to_kinds(desires)
    print(f"Matched kinds from desires: {kinds}")

    places_info = get_places(city, latitude, longitude, limit=limited_activities, kinds=kinds)

    return {
        "places": places_info,
        "number_of_activities": len([p for p in places_info if "error" not in p]),
        "matched_kinds": kinds,
    }


def itinerary_node(state: StateDict) -> dict:
    print("Itinerary node reached")

    schema = ItineraryOutput.model_json_schema()
    schema["required"] = list(schema["properties"].keys())

    response = cached_llm_call(
        model=OLLAMA_MODEL,
        system_prompt=ITINERARY_SYSTEM,
        user_prompt=build_itinerary_prompt(state),
        response_schema=schema,
    )
    output = ItineraryOutput.model_validate(response)
    return {"final_response": output.itinerary, "source_node": "itinerary"}


class TripPilotGraph:
    """
    A graph representing the TripPilot agent.
    """
    def __init__(self):
        self.builder = StateGraph(StateDict)
        self.builder.add_node("extract_preferences", extract_preferences_node)
        self.builder.add_node("validate", validate_preferences_node)
        self.builder.add_node("clarification", clarification_node)
        self.builder.add_node("weather", weather_node)
        self.builder.add_node("weather_error", weather_error_node)
        self.builder.add_node("places", places_node)
        self.builder.add_node("budget", budget_node)
        self.builder.add_node("itinerary", itinerary_node)

        self.builder.add_edge(START, "extract_preferences")
        self.builder.add_edge("extract_preferences", "validate")
        self.builder.add_conditional_edges(
            "validate",
            route_after_validation,
            {"clarification": "clarification", "weather": "weather"},
        )
        self.builder.add_edge("clarification", END)
        self.builder.add_conditional_edges(
            "weather",
            route_after_weather,
            {"weather_error": "weather_error", "places": "places"},
        )
        self.builder.add_edge("weather_error", END)
        self.builder.add_edge("places", "budget")
        self.builder.add_edge("budget", "itinerary")
        self.builder.add_edge("itinerary", END)

        self.graph = self.builder.compile()

    def invoke(self, entry: str) -> StateDict:
        """
        Invoke the graph with the given state.

        Args:
            entry (str): The city for which to fetch weather information.
        Returns:
            StateDict: The updated state of the agent after processing through the graph.
        """
        initial_state_dict = StateDict(entry=entry)
        return self.graph.invoke(initial_state_dict)