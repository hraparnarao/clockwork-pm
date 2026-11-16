"""
ClockWork PM – timesheet router.
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.routers.auth import get_current_user
from app.database import get_db
from datetime import date, timedelta
import json

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def _auth(request: Request):
    user = get_current_user(request)
    if not user:
        raise Exception("not_authed")
    return user


def _week_bounds(iso_week: str | None):
    """Return (monday, sunday) for the given YYYY-Www or today's week."""
    if iso_week:
        try:
            monday = date.fromisoformat(iso_week + "-1")  # ISO week Monday
        except Exception:
            monday = _this_monday()
    else:
        monday = _this_monday()
    sunday = monday + timedelta(days=6)
    return monday, sunday


def _this_monday():
    today = date.today()
    return today - timedelta(days=today.weekday())


def _get_entries(user_id: int, monday: date, sunday: date):
    conn = get_db()
    rows = conn.execute("""
        SELECT te.*, p.name AS project_name, sp.name AS sub_project_name
        FROM timesheet_entries te
        JOIN projects p ON p.id = te.project_id
        LEFT JOIN sub_projects sp ON sp.id = te.sub_project_id
        WHERE te.user_id = ? AND te.entry_date >= ? AND te.entry_date <= ?
        ORDER BY te.entry_date, te.id
    """, (user_id, monday.isoformat(), sunday.isoformat())).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_projects():
    conn = get_db()
    projects = conn.execute("SELECT * FROM projects WHERE is_active=1 ORDER BY name").fetchall()
    subs = conn.execute("SELECT * FROM sub_projects WHERE is_active=1 ORDER BY project_id, name").fetchall()
    conn.close()
    return [dict(p) for p in projects], [dict(s) for s in subs]


@router.get("/timesheet", response_class=HTMLResponse)
def timesheet_page(request: Request, week: str = None):
    try:
        user = _auth(request)
    except Exception:
        return RedirectResponse("/login?next=/timesheet", status_code=302)

    monday, sunday = _week_bounds(week)
    entries = _get_entries(user["id"], monday, sunday)
    projects, subs = _get_projects()

    # Build week days Mon-Fri
    week_days = []
    for i in range(5):
        d = monday + timedelta(days=i)
        day_entries = [e for e in entries if e["entry_date"] == d.isoformat()]
        total = sum(e["hours"] for e in day_entries)
        week_days.append({
            "date": d.isoformat(),
            "label": f"{DAY_NAMES[d.weekday()]} {d.strftime('%d %b')}",
            "entries": day_entries,
            "total": total,
        })

    # Week status: all Draft, all Submitted, or mixed
    statuses = set(e["status"] for e in entries)
    if not entries:
        week_status = "empty"
    elif statuses == {"Submitted"}:
        week_status = "Submitted"
    elif "Submitted" in statuses:
        week_status = "partial"
    else:
        week_status = "Draft"

    prev_week = (monday - timedelta(weeks=1)).strftime("%G-W%V")
    next_week = (monday + timedelta(weeks=1)).strftime("%G-W%V")
    today = date.today()
    is_future = monday > today

    subs_by_project = {}
    for s in subs:
        subs_by_project.setdefault(s["project_id"], []).append(s)

    return templates.TemplateResponse("timesheet.html", {
        "request": request,
        "current_user": user,
        "active": "timesheet",
        "week_days": week_days,
        "week_label": f"{monday.strftime('%d %b')} – {sunday.strftime('%d %b %Y')}",
        "prev_week": prev_week,
        "next_week": next_week,
        "is_future": is_future,
        "week_status": week_status,
        "today": today.isoformat(),
        "monday": monday.isoformat(),
        "projects": projects,
        "subs_by_project": subs_by_project,
        "subs_json": json.dumps(subs_by_project),
    })


# ── API endpoints used by the page JS ─────────────────────────────────────────

@router.post("/api/entries", response_class=JSONResponse)
async def create_entry(request: Request):
    try:
        user = _auth(request)
    except Exception:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    data = await request.json()
    err = _validate_entry(data)
    if err:
        return JSONResponse({"error": err}, status_code=400)

    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO timesheet_entries
        (user_id, entry_date, project_id, sub_project_id, category, activity, hours, status)
        VALUES (?,?,?,?,?,?,?,?)
    """, (
        user["id"],
        data["entry_date"],
        data["project_id"],
        data.get("sub_project_id") or None,
        data["category"],
        data.get("activity", ""),
        data["hours"],
        "Draft",
    ))
    entry_id = c.lastrowid
    row = conn.execute("""
        SELECT te.*, p.name AS project_name, sp.name AS sub_project_name
        FROM timesheet_entries te
        JOIN projects p ON p.id = te.project_id
        LEFT JOIN sub_projects sp ON sp.id = te.sub_project_id
        WHERE te.id = ?
    """, (entry_id,)).fetchone()
    conn.commit()
    conn.close()
    return JSONResponse(dict(row))


@router.put("/api/entries/{entry_id}", response_class=JSONResponse)
async def update_entry(entry_id: int, request: Request):
    try:
        user = _auth(request)
    except Exception:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    data = await request.json()
    conn = get_db()
    existing = conn.execute("SELECT * FROM timesheet_entries WHERE id=? AND user_id=?",
                            (entry_id, user["id"])).fetchone()
    if not existing:
        conn.close()
        return JSONResponse({"error": "Not found"}, status_code=404)

    err = _validate_entry(data)
    if err:
        conn.close()
        return JSONResponse({"error": err}, status_code=400)

    conn.execute("""
        UPDATE timesheet_entries
        SET entry_date=?, project_id=?, sub_project_id=?, category=?, activity=?, hours=?,
            updated_at=datetime('now')
        WHERE id=? AND user_id=?
    """, (
        data["entry_date"],
        data["project_id"],
        data.get("sub_project_id") or None,
        data["category"],
        data.get("activity", ""),
        data["hours"],
        entry_id, user["id"],
    ))
    row = conn.execute("""
        SELECT te.*, p.name AS project_name, sp.name AS sub_project_name
        FROM timesheet_entries te
        JOIN projects p ON p.id = te.project_id
        LEFT JOIN sub_projects sp ON sp.id = te.sub_project_id
        WHERE te.id = ?
    """, (entry_id,)).fetchone()
    conn.commit()
    conn.close()
    return JSONResponse(dict(row))


@router.delete("/api/entries/{entry_id}", response_class=JSONResponse)
def delete_entry(entry_id: int, request: Request):
    try:
        user = _auth(request)
    except Exception:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    conn = get_db()
    existing = conn.execute("SELECT * FROM timesheet_entries WHERE id=? AND user_id=?",
                            (entry_id, user["id"])).fetchone()
    if not existing:
        conn.close()
        return JSONResponse({"error": "Not found"}, status_code=404)

    conn.execute("DELETE FROM timesheet_entries WHERE id=?", (entry_id,))
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})


@router.post("/api/entries/submit-week", response_class=JSONResponse)
async def submit_week(request: Request):
    try:
        user = _auth(request)
    except Exception:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    data = await request.json()
    monday = data.get("monday")
    sunday_dt = date.fromisoformat(monday) + timedelta(days=6)
    conn = get_db()
    conn.execute("""
        UPDATE timesheet_entries
        SET status='Submitted', updated_at=datetime('now')
        WHERE user_id=? AND entry_date >= ? AND entry_date <= ? AND status='Draft'
    """, (user["id"], monday, sunday_dt.isoformat()))
    conn.commit()
    conn.close()
    return JSONResponse({"ok": True})


@router.get("/api/entries/yesterday", response_class=JSONResponse)
def copy_yesterday(request: Request, ref_date: str):
    """Return entries from the day before ref_date."""
    try:
        user = _auth(request)
    except Exception:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    d = date.fromisoformat(ref_date)
    yesterday = (d - timedelta(days=1)).isoformat()
    conn = get_db()
    rows = conn.execute("""
        SELECT te.*, p.name AS project_name, sp.name AS sub_project_name
        FROM timesheet_entries te
        JOIN projects p ON p.id = te.project_id
        LEFT JOIN sub_projects sp ON sp.id = te.sub_project_id
        WHERE te.user_id=? AND te.entry_date=?
    """, (user["id"], yesterday)).fetchall()
    conn.close()
    return JSONResponse([dict(r) for r in rows])


def _validate_entry(data: dict) -> str | None:
    """Return error string or None."""
    try:
        hours = float(data.get("hours", 0))
    except (TypeError, ValueError):
        return "Hours must be a number."

    if hours < 0.25 or hours > 12:
        return "Hours must be between 0.25 and 12."

    # Must be a multiple of 0.25
    if round(hours * 4) != hours * 4:
        return "Hours must be in 0.25 increments."

    entry_date = data.get("entry_date", "")
    try:
        d = date.fromisoformat(entry_date)
    except ValueError:
        return "Invalid date."

    if d > date.today():
        return "Cannot enter hours for a future date."

    if not data.get("project_id"):
        return "Project is required."

    return None
