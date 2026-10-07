import calendar
from datetime import date

import requests

from config import MOIS

ARCHIVE_YEARS_BACK = 5  # nombre d'années d'historique à moyenner



def _fetch_month_archive(latitude: float, longitude: float, year: int, month: int) -> dict:
    """Fetches daily archive data for an entire month."""
    last_day = calendar.monthrange(year, month)[1]
    start = f"{year}-{month:02d}-01"
    end = f"{year}-{month:02d}-{last_day:02d}"

    response = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start,
            "end_date": end,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto",
        },
        timeout=5,
    )
    response.raise_for_status()
    return response.json()


def _score_day(temp_max: float, precip: float) -> float:
    """
    Higher is better. Simple heuristic: reward warmth, penalize rain.
    Tune the weights if the recommendations feel off.
    """
    return temp_max - (precip * 3)


def find_best_period(
    latitude: float,
    longitude: float,
    target_year: int,
    target_month: int,
    duration_days: int,
    years_back: int = 5,
) -> dict:
    """
    Finds the best `duration_days`-long window within `target_month`,
    based on averaged historical weather over the past `years_back` years.

    Returns the chosen date range plus its average climate.
    """
    last_day = calendar.monthrange(target_year, target_month)[1]
    duration_days = min(duration_days, last_day)  # sécurité

    # day_scores[d] = liste des scores du jour `d` du mois, sur toutes les années
    day_scores: dict[int, list[float]] = {d: [] for d in range(1, last_day + 1)}
    day_climate: dict[int, dict[str, list[float]]] = {
        d: {"temp_max": [], "temp_min": [], "precip": []} for d in range(1, last_day + 1)
    }

    for offset in range(1, years_back + 1):
        past_year = target_year - offset
        try:
            archive = _fetch_month_archive(latitude, longitude, past_year, target_month)
        except requests.exceptions.RequestException:
            continue

        daily = archive.get("daily", {})
        dates = daily.get("time", [])
        temp_maxs = daily.get("temperature_2m_max", [])
        temp_mins = daily.get("temperature_2m_min", [])
        precips = daily.get("precipitation_sum", [])

        for i, date_str in enumerate(dates):
            day_of_month = int(date_str.split("-")[2])
            if temp_maxs[i] is None or precips[i] is None:
                continue
            day_scores[day_of_month].append(_score_day(temp_maxs[i], precips[i]))
            day_climate[day_of_month]["temp_max"].append(temp_maxs[i])
            day_climate[day_of_month]["temp_min"].append(temp_mins[i] or 0)
            day_climate[day_of_month]["precip"].append(precips[i])

    # moyenne du score par jour-du-mois
    avg_score_by_day = {
        d: (sum(scores) / len(scores) if scores else float("-inf"))
        for d, scores in day_scores.items()
    }

    # glisse une fenêtre de `duration_days` et cherche la meilleure somme de score
    best_start_day = 1
    best_total_score = float("-inf")

    for start_day in range(1, last_day - duration_days + 2):
        window = range(start_day, start_day + duration_days)
        total_score = sum(avg_score_by_day[d] for d in window)
        if total_score > best_total_score:
            best_total_score = total_score
            best_start_day = start_day

    # agrège le climat de la fenêtre retenue
    window_days = range(best_start_day, best_start_day + duration_days)
    all_temp_max = [t for d in window_days for t in day_climate[d]["temp_max"]]
    all_temp_min = [t for d in window_days for t in day_climate[d]["temp_min"]]
    all_precip = [p for d in window_days for p in day_climate[d]["precip"]]

    start_date = f"{target_year}-{target_month:02d}-{best_start_day:02d}"
    end_day = best_start_day + duration_days - 1
    end_date = f"{target_year}-{target_month:02d}-{end_day:02d}"

    return {
        "start_time": start_date,
        "end_time": end_date,
        "number_of_days": duration_days,
        "weather": {
            "avg_temp_max": round(sum(all_temp_max) / len(all_temp_max), 1) if all_temp_max else None,
            "avg_temp_min": round(sum(all_temp_min) / len(all_temp_min), 1) if all_temp_min else None,
            "avg_precipitation_mm": round(sum(all_precip) / len(all_precip), 1) if all_precip else None,
            "note": f"Meilleure période de {duration_days} jours trouvée dans le mois, basée sur {years_back} ans d'historique.",
        }
       
    }

def get_coordinates(query: str, country: str | None = None) -> tuple[float, float, str]:
    """
    Get the latitude and longitude for a given city OR country name
    using the Open-Meteo geocoding API.

    Args:
        query (str): A city name or a country name.
        country (str | None): Expected country (French name), used to pick
            the right homonym (e.g. Lisbonne, Portugal vs Lisbonne, Belgique).

    Returns:
        tuple[float, float, str]: latitude, longitude, and the resolved
        place name actually used (useful for logging/debugging).
    """
    try:
        response = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query, "count": 10, "language": "fr"},
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Unable to fetch location data: {e}")

    results = data.get("results")
    if not results:
        raise ValueError(f"No location data found for '{query}'.")

    if country and country != "unknown":
        same_country = [r for r in results if r.get("country", "").casefold() == country.casefold()]
        if same_country:
            results = same_country

    result = max(results, key=lambda r: r.get("population") or 0)
    return result["latitude"], result["longitude"], f"{result['name']}, {result.get('country', '')}"

def _same_period_past_years(start_time: str, end_time: str, years_back: int) -> list[tuple[str, str]]:
    """
    Given a future (or any) date range, returns the same calendar
    period for each of the `years_back` previous years.
    """
    start = date.fromisoformat(start_time)
    end = date.fromisoformat(end_time)
    periods = []

    for offset in range(1, years_back + 1):
        try:
            past_start = start.replace(year=start.year - offset)
            past_end = end.replace(year=end.year - offset)
        except ValueError:
            # cas du 29 février sur une année non bissextile
            continue
        periods.append((past_start.isoformat(), past_end.isoformat()))

    return periods


def _fetch_archive(latitude: float, longitude: float, start: str, end: str) -> dict:
    response = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start,
            "end_date": end,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
            "timezone": "auto",
        },
        timeout=5,
    )
    response.raise_for_status()
    return response.json()

def _aggregate_climate(archives: list[dict]) -> dict:
    """
    Averages temperature/precipitation across multiple past-year archives.
    """
    all_max_temps, all_min_temps, all_precip = [], [], []

    for archive in archives:
        daily = archive.get("daily", {})
        all_max_temps.extend(t for t in daily.get("temperature_2m_max", []) if t is not None)
        all_min_temps.extend(t for t in daily.get("temperature_2m_min", []) if t is not None)
        all_precip.extend(p for p in daily.get("precipitation_sum", []) if p is not None)

    if not all_max_temps:
        return {"error": "No historical data available for this period."}

    return {
        "avg_temp_max": round(sum(all_max_temps) / len(all_max_temps), 1),
        "avg_temp_min": round(sum(all_min_temps) / len(all_min_temps), 1),
        "avg_precipitation_mm": round(sum(all_precip) / len(all_precip), 1),
        "years_used": len(archives),
    }

def get_weather(city: str, country: str, start_time: str, end_time: str,
                 date_precise: bool, month: str, year: int,
                 number_of_days: int) -> dict:
    location_query = city if city != "unknown" else country
    if location_query == "unknown":
        return {"error": "Neither city nor country provided."}

    try:
        latitude, longitude, resolved_name = get_coordinates(location_query, country)
    except (RuntimeError, ValueError) as e:
        return {"error": str(e)}

    if date_precise and start_time != "unknown" and end_time != "unknown":
        periods = _same_period_past_years(start_time, end_time, ARCHIVE_YEARS_BACK)
        archives = []
        for past_start, past_end in periods:
            try:
                archives.append(_fetch_archive(latitude, longitude, past_start, past_end))
            except requests.exceptions.RequestException:
                continue
        climate_stats = _aggregate_climate(archives)
        climate = {
            "start_time": start_time,
            "end_time": end_time,
            "number_of_days": number_of_days,
            "weather": climate_stats,
        }
    elif month != "unknown" and year != "unknown":
        month_index = MOIS.index(month) + 1
        climate = find_best_period(latitude, longitude, int(year), month_index, number_of_days or 7)
    else:
        return {"error": "Not enough date information.", "latitude": latitude, "longitude": longitude}
    climate["latitude"] = latitude
    climate["longitude"] = longitude
    climate["resolved_location"] = resolved_name
    return climate
    