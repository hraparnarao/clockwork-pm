"""
ClockWork PM – reports router.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from app.routers.auth import get_current_user
from app.database import get_db
from datetime import date, timedelta
import io

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _scope_user_ids(user, conn):
    """Return the list of user IDs this user can see."""
    role = user["role"]
    uid  = user["id"]
    if role == "Admin":
        return [r["id"] for r in conn.execute("SELECT id FROM users WHERE is_active=1").fetchall()]
    elif role == "Manager":
        reports = [r["id"] for r in conn.execute("SELECT id FROM users WHERE manager_id=?", (uid,)).fetchall()]
        return [uid] + reports
    else:
        return [uid]


@router.get("/reports", response_class=HTMLResponse)
def reports_page(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login?next=/reports", status_code=302)

    conn = get_db()
    projects = conn.execute("SELECT * FROM projects WHERE is_active=1 ORDER BY name").fetchall()
    visible_ids = _scope_user_ids(user, conn)
    users = conn.execute(
        f"SELECT id, name FROM users WHERE id IN ({','.join('?'*len(visible_ids))}) AND is_active=1 ORDER BY name",
        visible_ids
    ).fetchall() if visible_ids else []
    conn.close()

    today = date.today()
    month_start = today.replace(day=1)

    return templates.TemplateResponse("reports.html", {
        "request": request,
        "current_user": user,
        "active": "reports",
        "projects": [dict(p) for p in projects],
        "users": [dict(u) for u in users],
        "default_from": month_start.isoformat(),
        "default_to":   today.isoformat(),
    })


@router.get("/api/reports/data", response_class=JSONResponse)
def reports_data(request: Request,
                 date_from: str = None,
                 date_to: str = None,
                 user_id: int = None,
                 project_id: int = None,
                 category: str = None):
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)

    conn = get_db()
    visible_ids = _scope_user_ids(user, conn)

    # Apply user filter (must be within scope)
    if user_id and user_id in visible_ids:
        filter_ids = [user_id]
    else:
        filter_ids = visible_ids

    if not filter_ids:
        conn.close()
        return JSONResponse({"rows": [], "total_hours": 0})

    today = date.today()
    date_from = date_from or today.replace(day=1).isoformat()
    date_to   = date_to   or today.isoformat()

    placeholders = ",".join("?" * len(filter_ids))
    params = filter_ids + [date_from, date_to]

    extra = ""
    if project_id:
        extra += " AND te.project_id = ?"
        params.append(project_id)
    if category:
        extra += " AND te.category = ?"
        params.append(category)

    rows = conn.execute(f"""
        SELECT te.id, te.entry_date, u.name AS user_name,
               p.name AS project_name, sp.name AS sub_project_name,
               te.category, te.activity, te.hours, te.status
        FROM timesheet_entries te
        JOIN users u    ON u.id = te.user_id
        JOIN projects p ON p.id = te.project_id
        LEFT JOIN sub_projects sp ON sp.id = te.sub_project_id
        WHERE te.user_id IN ({placeholders})
          AND te.entry_date >= ? AND te.entry_date <= ?
          {extra}
        ORDER BY te.entry_date DESC, u.name, te.id
    """, params).fetchall()

    conn.close()

    result = [dict(r) for r in rows]
    total = sum(r["hours"] for r in result)
    return JSONResponse({"rows": result, "total_hours": round(total, 2)})


@router.get("/api/reports/export")
def reports_export(request: Request,
                   date_from: str = None,
                   date_to: str = None,
                   user_id: int = None,
                   project_id: int = None,
                   category: str = None):
    """Export filtered report as Excel."""
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return JSONResponse({"error": "openpyxl not installed"}, status_code=500)

    # Reuse data logic
    data = reports_data(request, date_from, date_to, user_id, project_id, category)
    payload = data.body
    import json
    obj = json.loads(payload)
    rows = obj["rows"]

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Timesheet Report"

    headers = ["Date", "Person", "Project", "Sub-project", "Category", "Activity", "Hours", "Status"]
    purple = "8B1F6B"
    header_fill = PatternFill("solid", fgColor=purple)
    header_font = Font(bold=True, color="FFFFFF", size=11)

    for col_idx, h in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for row_idx, r in enumerate(rows, 2):
        ws.cell(row=row_idx, column=1, value=r["entry_date"])
        ws.cell(row=row_idx, column=2, value=r["user_name"])
        ws.cell(row=row_idx, column=3, value=r["project_name"])
        ws.cell(row=row_idx, column=4, value=r["sub_project_name"] or "")
        ws.cell(row=row_idx, column=5, value=r["category"])
        ws.cell(row=row_idx, column=6, value=r["activity"] or "")
        ws.cell(row=row_idx, column=7, value=r["hours"])
        ws.cell(row=row_idx, column=8, value=r["status"])

    # Totals row
    total_row = len(rows) + 2
    ws.cell(row=total_row, column=1, value="TOTAL").font = Font(bold=True)
    ws.cell(row=total_row, column=7, value=obj["total_hours"]).font = Font(bold=True)

    # Column widths
    widths = [12, 20, 18, 16, 12, 40, 8, 12]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    fname = f"timesheet_report_{date_from}_{date_to}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'}
    )
