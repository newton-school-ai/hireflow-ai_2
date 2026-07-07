from fastapi import FastAPI
from src.api.routes.profile import router as profile_router

app = FastAPI(title="HireFlow API")

app.include_router(profile_router, tags=["Profile"])


@app.get("/")
def health_check():
    return {"status": "ok"}
