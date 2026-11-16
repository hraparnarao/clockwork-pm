"""
ClockWork PM – dashboard router.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.routers.auth import get_current_user
from app.database import get_db
from datetime import date, timedelta

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _this_monday():
    today = date.today()
    return today - timedelta(days=today.weekday())


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login?next=/dashboard", status_code=302)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "current_user": user,
        "active": "dashboard",
    })


@router.get("/api/dashboard/data", response_class=JSONResponse)
def dashboard_data(request: Request):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    conn = get_db()
    today = date.today()
    monday = _this_monday()
    week_end = monday + timedelta(days=6)
    month_start = today.replace(day=1)

    # Determine which user IDs to show based on role
    uid = user["id"]
    role = user["role"]

    if role == "Admin":
        # All active users
        user_ids = [r["id"] for r in conn.execute("SELECT id FROM users WHERE is_active=1").fetchall()]
    elif role == "Manager":
        # Self + direct reports
        reports = [r["id"] for r in conn.execute("SELECT id FROM users WHERE manager_id=?", (uid,)).fetchall()]
        user_ids = [uid] + reports
    else:
        user_ids = [uid]

    placeholders = ",".join("?" * len(user_ids))

    # ── KPIs ──────────────────────────────────────────────────────────────────
    hours_this_week = conn.execute(
        f"SELECT COALESCE(SUM(hours),0) FROM timesheet_entries WHERE user_id IN ({placeholders}) AND entry_date >= ? AND entry_date <= ?",
        user_ids + [monday.isoformat(), week_end.isoformat()]
    ).fetchone()[0]

    hours_this_month = conn.execute(
        f"SELECT COALESCE(SUM(hours),0) FROM timesheet_entries WHERE user_id IN ({placeholders}) AND entry_date >= ?",
        user_ids + [month_start.isoformat()]
    ).fetchone()[0]

    billable_month = conn.execute(
        f"SELECT COALESCE(SUM(hours),0) FROM timesheet_entries WHERE user_id IN ({placeholders}) AND entry_date >= ? AND category='Billable'",
        user_ids + [month_start.isoformat()]
    ).fetchone()[0]

    billable_pct = round((billable_month / hours_this_month * 100) if hours_this_month > 0 else 0, 1)

    # Missing entry days this week (Mon-Fri up to today)
    days_in_week = []
    for i in range(5):
        d = monday + timedelta(days=i)
        if d <= today:
            days_in_week.append(d)

    missing_days = []
    for d in days_in_week:
        total = conn.execute(
            f"SELECT COALESCE(SUM(hours),0) FROM timesheet_entries WHERE user_id IN ({placeholders}) AND entry_date=?",
            user_ids + [d.isoformat()]
        ).fetchone()[0]
        if total == 0:
            missing_days.append(d.strftime("%a %d %b"))

    # ── Chart: billable vs non-billable (last 30 days) ─────────────────────────
    rows = conn.execute(
        f"""SELECT category, COALESCE(SUM(hours),0) as h
            FROM timesheet_entries
            WHERE user_id IN ({placeholders}) AND entry_date >= ?
            GROUP BY category""",
        user_ids + [(today - timedelta(days=30)).isoformat()]
    ).fetchall()
    cat_totals = {r["category"]: r["h"] for r in rows}

    # ── Chart: hours by project (last 30 days) ─────────────────────────────────
    proj_rows = conn.execute(
        f"""SELECT p.name, COALESCE(SUM(te.hours),0) as h
            FROM timesheet_entries te JOIN projects p ON p.id=te.project_id
            WHERE te.user_id IN ({placeholders}) AND te.entry_date >= ?
            GROUP BY p.id ORDER BY h DESC LIMIT 8""",
        user_ids + [(today - timedelta(days=30)).isoformat()]
    ).fetchall()
    hours_by_project = [{"name": r["name"], "hours": r["h"]} for r in proj_rows]

    # ── Chart: hours by day (this week) ────────────────────────────────────────
    day_rows = conn.execute(
        f"""SELECT entry_date, COALESCE(SUM(hours),0) as h
            FROM timesheet_entries
            WHERE user_id IN ({placeholders}) AND entry_date >= ? AND entry_date <= ?
            GROUP BY entry_date ORDER BY entry_date""",
        user_ids + [monday.isoformat(), week_end.isoformat()]
    ).fetchall()
    hours_by_day = {r["entry_date"]: r["h"] for r in day_rows}
    # Fill all 5 weekdays
    day_chart = []
    day_labels = ["Mon", "Tue", "Wed", "Thu", "Fri"]
    for i in range(5):
        d = monday + timedelta(days=i)
        day_chart.append({"day": day_labels[i], "hours": hours_by_day.get(d.isoformat(), 0)})

    # ── Manager/Admin: hours by person ────────────────────────────────────────
    hours_by_person = []
    not_submitted = []
    if role in ("Manager", "Admin"):
        person_rows = conn.execute(
            f"""SELECT u.name, COALESCE(SUM(te.hours),0) as h
                FROM timesheet_entries te JOIN users u ON u.id=te.user_id
                WHERE te.user_id IN ({placeholders}) AND te.entry_date >= ? AND te.entry_date <= ?
                GROUP BY te.user_id ORDER BY h DESC""",
            user_ids + [monday.isoformat(), week_end.isoformat()]
        ).fetchall()
        hours_by_person = [{"name": r["name"], "hours": r["h"]} for r in person_rows]

        # Users who haven't submitted this week
        for uid2 in user_ids:
            submitted = conn.execute(
                "SELECT COUNT(*) FROM timesheet_entries WHERE user_id=? AND entry_date>=? AND entry_date<=? AND status='Submitted'",
                (uid2, monday.isoformat(), week_end.isoformat())
            ).fetchone()[0]
            if submitted == 0:
                u = conn.execute("SELECT name FROM users WHERE id=?", (uid2,)).fetchone()
                if u:
                    not_submitted.append(u["name"])

    conn.close()

    return JSONResponse({
        "kpi": {
            "hours_this_week": round(hours_this_week, 2),
            "hours_this_month": round(hours_this_month, 2),
            "billable_pct": billable_pct,
            "missing_days": len(missing_days),
        },
        "missing_day_names": missing_days,
        "cat_totals": cat_totals,
        "hours_by_project": hours_by_project,
        "day_chart": day_chart,
        "hours_by_person": hours_by_person,
        "not_submitted": not_submitted,
        "role": role,
    })
