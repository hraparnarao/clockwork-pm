"""
ClockWork PM – admin router (Projects + Users).
Accessible by Manager and Admin roles.
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from app.routers.auth import get_current_user
from app.auth import hash_password
from app.database import get_db

router = APIRouter(prefix="/admin")
templates = Jinja2Templates(directory="app/templates")


def _require_manager(request: Request):
    user = get_current_user(request)
    if not user or user["role"] not in ("Manager", "Admin"):
        return None
    return user


def _require_admin(request: Request):
    user = get_current_user(request)
    if not user or user["role"] != "Admin":
        return None
    return user


# ══════════════════════════════════════════════════════════════════════════════
# PROJECTS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/projects", response_class=HTMLResponse)
def projects_page(request: Request):
    user = _require_manager(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    conn = get_db()
    projects = conn.execute("SELECT * FROM projects ORDER BY name").fetchall()
    subs = conn.execute("SELECT * FROM sub_projects ORDER BY project_id, name").fetchall()
    conn.close()

    subs_by_project = {}
    for s in subs:
        subs_by_project.setdefault(s["project_id"], []).append(dict(s))

    return templates.TemplateResponse("admin_projects.html", {
        "request": request,
        "current_user": user,
        "active": "admin-projects",
        "projects": [dict(p) for p in projects],
        "subs_by_project": subs_by_project,
    })


@router.post("/api/projects", response_class=JSONResponse)
async def create_project(request: Request):
    user = _require_manager(request)
    if not user:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    data = await request.json()
    name = data.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Name is required"}, status_code=400)
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO projects (name, client, is_active) VALUES (?,?,1)",
              (name, data.get("client", "").strip()))
    pid = c.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    conn.close()
    return JSONResponse(dict(row))


@router.put("/api/projects/{pid}", response_class=JSONResponse)
async def update_project(pid: int, request: Request):
    user = _require_manager(request)
    if not user:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    data = await request.json()
    conn = get_db()
    conn.execute("UPDATE projects SET name=?, client=?, is_active=? WHERE id=?",
                 (data.get("name","").strip(), data.get("client","").strip(),
                  1 if data.get("is_active", True) else 0, pid))
    conn.commit()
    row = conn.execute("SELECT * FROM projects WHERE id=?", (pid,)).fetchone()
    conn.close()
    return JSONResponse(dict(row))


# Sub-projects
@router.post("/api/projects/{pid}/subs", response_class=JSONResponse)
async def create_sub(pid: int, request: Request):
    user = _require_manager(request)
    if not user:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    data = await request.json()
    name = data.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Name is required"}, status_code=400)
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO sub_projects (project_id, name) VALUES (?,?)", (pid, name))
    sid = c.lastrowid
    conn.commit()
    row = conn.execute("SELECT * FROM sub_projects WHERE id=?", (sid,)).fetchone()
    conn.close()
    return JSONResponse(dict(row))


@router.delete("/api/subs/{sid}", response_class=JSONResponse)
def delete_sub(sid: int, request: Request):
    user = _require_manager(request)
    if not user:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    conn = get_db()

    # Check whether any timesheet entries reference this sub-project
    ref_count = conn.execute(
        "SELECT COUNT(*) FROM timesheet_entries WHERE sub_project_id=?", (sid,)
    ).fetchone()[0]

    if ref_count > 0:
        # Soft-delete: mark inactive so it vanishes from dropdowns but entries keep their name
        conn.execute("UPDATE sub_projects SET is_active=0 WHERE id=?", (sid,))
        conn.commit()
        conn.close()
        return JSONResponse({"ok": True, "soft": True,
                             "message": "Sub-project has existing entries, so it was deactivated instead of deleted."})
    else:
        conn.execute("DELETE FROM sub_projects WHERE id=?", (sid,))
        conn.commit()
        conn.close()
        return JSONResponse({"ok": True, "soft": False})


# ══════════════════════════════════════════════════════════════════════════════
# USERS
# ══════════════════════════════════════════════════════════════════════════════

@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    user = _require_admin(request)
    if not user:
        return RedirectResponse("/login", status_code=302)

    conn = get_db()
    users = conn.execute("""
        SELECT u.*, m.name AS manager_name
        FROM users u LEFT JOIN users m ON m.id = u.manager_id
        ORDER BY u.name
    """).fetchall()
    managers = conn.execute("SELECT id, name FROM users WHERE role IN ('Manager','Admin') AND is_active=1 ORDER BY name").fetchall()
    conn.close()

    return templates.TemplateResponse("admin_users.html", {
        "request": request,
        "current_user": user,
        "active": "admin-users",
        "users": [dict(u) for u in users],
        "managers": [dict(m) for m in managers],
    })


@router.post("/api/users", response_class=JSONResponse)
async def create_user(request: Request):
    user = _require_admin(request)
    if not user:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    data = await request.json()
    name  = data.get("name", "").strip()
    email = data.get("email", "").strip().lower()
    pw    = data.get("password", "").strip()
    role  = data.get("role", "Employee")
    mgr   = data.get("manager_id") or None

    if not name or not email or not pw:
        return JSONResponse({"error": "Name, email and password are required"}, status_code=400)

    conn = get_db()
    existing = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if existing:
        conn.close()
        return JSONResponse({"error": "Email already exists"}, status_code=400)

    c = conn.cursor()
    c.execute("INSERT INTO users (name, email, password_hash, role, manager_id, is_active) VALUES (?,?,?,?,?,1)",
              (name, email, hash_password(pw), role, mgr))
    uid = c.lastrowid
    conn.commit()
    row = conn.execute("SELECT u.*, m.name AS manager_name FROM users u LEFT JOIN users m ON m.id=u.manager_id WHERE u.id=?", (uid,)).fetchone()
    conn.close()
    return JSONResponse(dict(row))


@router.put("/api/users/{uid}", response_class=JSONResponse)
async def update_user(uid: int, request: Request):
    user = _require_admin(request)
    if not user:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    data = await request.json()
    conn = get_db()

    updates = {
        "name":       data.get("name", "").strip(),
        "email":      data.get("email", "").strip().lower(),
        "role":       data.get("role", "Employee"),
        "manager_id": data.get("manager_id") or None,
        "is_active":  1 if data.get("is_active", True) else 0,
    }

    new_pw = data.get("password", "").strip()
    if new_pw:
        conn.execute("""UPDATE users SET name=?,email=?,role=?,manager_id=?,is_active=?,password_hash=? WHERE id=?""",
                     (updates["name"], updates["email"], updates["role"],
                      updates["manager_id"], updates["is_active"], hash_password(new_pw), uid))
    else:
        conn.execute("""UPDATE users SET name=?,email=?,role=?,manager_id=?,is_active=? WHERE id=?""",
                     (updates["name"], updates["email"], updates["role"],
                      updates["manager_id"], updates["is_active"], uid))

    conn.commit()
    row = conn.execute("SELECT u.*, m.name AS manager_name FROM users u LEFT JOIN users m ON m.id=u.manager_id WHERE u.id=?", (uid,)).fetchone()
    conn.close()
    return JSONResponse(dict(row))
