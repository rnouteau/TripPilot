import json
from datetime import date

from .state import StateDict

EXTRACT_PREFERENCES_SYSTEM = (
        "You are a travel assistant that extracts structured data from a user "
        "request. You read between the lines and infer missing information "
        "when it is reasonably certain. You always output valid JSON."
    )

def build_extract_preferences_prompt(state: StateDict, today: date, next_monday: date) -> str:
    """
    Build a prompt for extracting travel preferences from a user request.

    Args:
        user_request (str): The user's travel request.
    
    Returns:
        str: The constructed prompt.
    """

    return f"""Today is {today.isoformat()} ({today.strftime('%A')}).
Monday of next week is {next_monday.isoformat()}.

Extract the travel information from the request below.

Rules:
- "ville": destination city, or null.
- "pays": destination country. If a city is given, INFER its country
  (e.g. Paris -> France, Lisbonne -> Portugal). If the city is ambiguous, use
  the most famous one.
- "date_debut" / "date_fin": ISO format YYYY-MM-DD, never free text.
  Resolve relative expressions from today's date:
  "next week" -> start on Monday of next week, end 7 days later;
  "this weekend" -> next Saturday and Sunday;
  "in July" with no day -> first day of July, and the year is the current one
  if July is not past yet, otherwise next year.
  Use null only if nothing allows an estimate.
- "date_precise": true if the user gave an exact day or date range, false if
  they only mentioned a month or a vague period (e.g. "in June", "next month").
- "nombre_de_jours": duration in days if stated or deducible, otherwise null.
- "nombre_de_voyageurs": number of travelers. "I want to travel", "je veux
  voyager" -> 1. "with my wife" -> 2. "family of four" -> 4.
- "envies": if the user mentions specific desires, extract them as a list of strings, otherwise null.
- "budget": if the user mentions a budget, extract it as a number in euros, otherwise null.
- "mois_vise": the target month in French (e.g. "juin"), extracted whenever
  a month is mentioned — REGARDLESS of whether an exact day is also given.
- "annee_visee": the target year, inferred from context if not explicit
  (assume the current or next occurrence of that month, like for dates).

Return ONLY a JSON object with exactly these keys: ville, pays, date_debut,
date_fin, date_precise, nombre_de_jours, nombre_de_voyageurs, envies, budget,
mois_vise, annee_visee.

Request: {state['entry']}
"""


# agent/prompts.py (ajout)

MATCH_DESIRES_SYSTEM = (
    "You are an assistant that maps a traveler's desires to OpenTripMap "
    "category tags (kinds). You only use tags from the provided list. "
    "You always output valid JSON."
)

# Sous-ensemble utile de la taxonomie OpenTripMap (https://opentripmap.io/docs#/Categories)
OPENTRIPMAP_KINDS = [
    "cultural", "historic", "architecture", "museums", "theatres_and_entertainments",
    "religion", "natural", "beaches", "water", "sport", "amusements",
    "shops", "foods", "view_points", "gardens_and_parks", "monuments_and_memorials",
]

def build_match_desires_prompt(desires: list[str]) -> str:
    desires_str = ", ".join(desires)
    kinds_str = ", ".join(OPENTRIPMAP_KINDS)
    return f"""The traveler mentioned these desires: {desires_str}

Available category tags: {kinds_str}

Select ONLY the tags from the list above that are relevant to these desires.
Return a JSON object with one key "kinds", an array of selected tag strings
(use exact spelling from the list, no invented tags).
"""


ITINERARY_SYSTEM = (
    "Tu es TripPilot, un assistant voyage francophone. Tu rédiges des itinéraires "
    "clairs, concrets et agréables à lire. Tu t'appuies UNIQUEMENT sur les données "
    "fournies (lieux, météo, budget) : n'invente pas de monuments ou de restaurants "
    "absents de la liste. Tu peux regrouper des visites proches le même jour. "
    "Tu réponds toujours en français, au format JSON demandé."
)


def build_itinerary_prompt(state: StateDict) -> str:
    places = [p for p in state.get("places", []) if "error" not in p]
    desires = state.get("desires") or []
    matched_kinds = state.get("matched_kinds") or []
    weather = state.get("weather") or {}

    return f"""Rédige l'itinéraire de voyage final à partir des données ci-dessous.

Demande d'origine du voyageur : {state["entry"]}

Destination : {state["city"]}, {state["country"]}
Période : du {state["start_time"]} au {state["end_time"]} ({state["number_of_days"]} jour(s))
Voyageurs : {state["number_of_travelers"]}
Budget (indication) : {state["budget"]}
Envies exprimées : {", ".join(desires) if desires else "non précisées"}
Catégories d'activités retenues : {", ".join(matched_kinds) if matched_kinds else "toutes"}

Météo (moyennes / contexte climatique) :
{json.dumps(weather, ensure_ascii=False, indent=2)}

Lieux et activités disponibles (utilise ces noms, répartis sur les jours) :
{json.dumps(places, ensure_ascii=False, indent=2)}

Consignes pour le champ "itinerary" :
- Structure jour par jour : "## Jour 1 — …", "## Jour 2 — …", etc. (autant de jours que number_of_days).
- Pour chaque jour : matin / après-midi / soir (ou équivalent), avec les lieux de la liste.
- Commence par un court paragraphe d'introduction (destination, ambiance, météo attendue).
- Termine par un paragraphe "Budget et conseils" reprenant l'estimation budget et 2–3 conseils pratiques.
- Si peu de lieux par rapport au nombre de jours, propose des temps libres ou flâneries sans inventer de nouveaux POI nommés.
- Ton chaleureux mais concis (pas de listes à puces interminables).

Retourne UNIQUEMENT un objet JSON avec la clé "itinerary" (texte markdown en français).
"""