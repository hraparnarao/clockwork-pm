"""
ClockWork PM – FastAPI application entry point.
"""
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from app.database import init_db, get_db
from app.routers import auth, timesheet, dashboard, reports, admin
from seed import seed
import bcrypt as _bcrypt

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
    seed()


@app.get("/")
def root(request: Request):
    return RedirectResponse("/timesheet")


@app.get("/debug-auth")
def debug_auth():
    conn = get_db()
    row = conn.execute("SELECT id, name, email, password_hash FROM users WHERE email=?",
                       ("aparna@vineinfotech.com",)).fetchone()
    conn.close()
    if not row:
        return JSONResponse({"error": "user not found"})
    hashed = row["password_hash"]
    test = _bcrypt.checkpw(b"password123", hashed.encode())
    return JSONResponse({
        "found": True,
        "email": row["email"],
        "hash_prefix": hashed[:7],
        "hash_len": len(hashed),
        "password_check": test,
    })
