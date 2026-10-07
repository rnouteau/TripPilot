from typing import Optional

from pydantic import BaseModel, Field


class PlanTripRequest(BaseModel):
    query: str = Field(min_length=1)


class PlanTripResponse(BaseModel):
    itinerary: Optional[str] = None
    clarification_needed: Optional[str] = None
    error: Optional[str] = None
    weather: Optional[dict] = None
    budget: Optional[str] = None
    places: Optional[list[dict]] = None
