from fastapi import FastAPI

from api import router

app = FastAPI(title="TripPilot")
app.include_router(router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
