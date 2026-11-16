"""
ClockWork PM – FastAPI application entry point.
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from app.database import init_db
from app.routers import auth, timesheet, dashboard, reports, admin

app = FastAPI(title="ClockWork PM")

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(auth.router)
app.include_router(timesheet.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(admin.router)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/")
def root(request: Request):
    return RedirectResponse("/timesheet")
