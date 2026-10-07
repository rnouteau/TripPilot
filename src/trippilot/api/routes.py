from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException

from agent import StateDict, TripPilotGraph

from .schemas import PlanTripRequest, PlanTripResponse

router = APIRouter()


@lru_cache
def get_graph() -> TripPilotGraph:
    return TripPilotGraph()


def state_to_response(state: StateDict) -> PlanTripResponse:
    source = state.get("source_node")
    message = state.get("final_response")
    if source not in ("itinerary", "clarification", "weather_error") or not message:
        raise HTTPException(status_code=500, detail="Le graphe s'est terminé sans réponse finale.")

    weather = state.get("weather")
    budget = state.get("budget")
    return PlanTripResponse(
        itinerary=message if source == "itinerary" else None,
        clarification_needed=message if source == "clarification" else None,
        error=message if source == "weather_error" else None,
        weather=weather if isinstance(weather, dict) and "error" not in weather else None,
        budget=budget if budget and budget != "unknown" else None,
        places=state.get("places"),
    )


@router.post("/plan-trip", response_model=PlanTripResponse)
def plan_trip(request: PlanTripRequest, graph: TripPilotGraph = Depends(get_graph)) -> PlanTripResponse:
    return state_to_response(graph.invoke(request.query))
