from typing import Annotated, Any, Optional, TypedDict

from pydantic import BaseModel


class StateDict(TypedDict):
    """A dictionary representing the state of the agent."""
    entry: str
    country: str
    city: str
    month: str
    year: str
    start_time: str
    end_time: str
    number_of_travelers: int
    number_of_days: int
    places: list[dict]  # List of places with name, category, and rating
    number_of_activities: int
    weather: Annotated[Any, "weather information"]  # This can be a dictionary or any other type depending on your needs
    budget: str  # Placeholder for budget estimation
    desires: Annotated[Any, "user desires/preferences"]  # This can be a list of strings or any other type depending on your needs
    missing_fields: list[str]
    final_response: Optional[str]
    source_node: Optional[str]  # terminal node that wrote final_response: clarification, weather_error or itinerary
    latitude: Optional[float]
    longitude: Optional[float]
    matched_kinds: Optional[list[str]]


class DesiresMatch(BaseModel):
    kinds: list[str] = []