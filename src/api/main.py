from fastapi import FastAPI

from src.api.routes.applications import router as applications_router
from src.api.routes.profile import router as profile_router
from src.api.routes.reports import router as reports_router
from src.api.routes.weekly_plan import router as weekly_plan_router
from src.api.routes.hiring import router as hiring_router

app = FastAPI(title="HireFlow API")

app.include_router(applications_router)
app.include_router(profile_router)
app.include_router(weekly_plan_router)
app.include_router(reports_router)
app.include_router(hiring_router)


@app.get("/")
def health_check():
    return {"status": "ok"}
