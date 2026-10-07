import os

import requests
from dotenv import load_dotenv

load_dotenv()
    
OPENTRIPMAP_API_KEY = os.getenv("OPENTRIPMAP_API_KEY")
BASE_URL = "https://api.opentripmap.com/0.1/en/places"


def get_places(city: str, latitude: float, longitude: float, limit: int = 10, kinds: list[str] | None = None) -> list[dict]:
    params = {
        "radius": 100000,
        "lon": longitude,
        "lat": latitude,
        "rate": 3,
        "limit": limit,
        "apikey": OPENTRIPMAP_API_KEY,
    }
    if kinds:
        params["kinds"] = ",".join(kinds)  # OpenTripMap accepte une liste séparée par des virgules

    try:
        response = requests.get(f"{BASE_URL}/radius", params=params, timeout=5)
        response.raise_for_status()
        raw_places = response.json().get("features", [])
    except requests.exceptions.RequestException as e:
        return [{"error": f"Unable to fetch places: {e}"}]

    places = []
    for place in raw_places:
        props = place.get("properties", {})
        places.append({
            "name": props.get("name", "Unknown"),
            "kinds": props.get("kinds", ""),
            "rate": props.get("rate", 0),
        })

    return places