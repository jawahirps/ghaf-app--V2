"""
Ghaf App — FastAPI application entrypoint.

Run with:
    uvicorn app.main:app --reload --port 8000
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .database import SessionLocal, init_db
from .routers import analytics, auth, clinical_profiles, dha_sync, facilities, reports
from .seed import run_seed

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    description="Core API for clinical profiles, login tracking, and the DHA XML Sync pipeline.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    db = SessionLocal()
    try:
        run_seed(db)
    finally:
        db.close()


@app.get("/api/health", tags=["health"])
def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "environment": settings.ENVIRONMENT}


app.include_router(auth.router)
app.include_router(clinical_profiles.router)
app.include_router(dha_sync.router)
app.include_router(analytics.router)
app.include_router(facilities.router)
app.include_router(reports.router)
