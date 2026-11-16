"""
ClockWork PM – auth router (login / logout).
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from app.auth import (
    verify_password, get_user_by_email,
    create_session_token, decode_session_token,
    get_user_by_id, SESSION_COOKIE,
)

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def get_current_user(request: Request):
    """Return user row or None from session cookie."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    uid = decode_session_token(token)
    if not uid:
        return None
    return get_user_by_id(uid)


def require_user(request: Request):
    """Return user or raise redirect (used in deps)."""
    user = get_current_user(request)
    if not user:
        raise Exception("not_authed")
    return user


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/"):
    user = get_current_user(request)
    if user:
        return RedirectResponse(next or "/timesheet", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "next": next})


@router.post("/login", response_class=HTMLResponse)
def login_post(request: Request,
               email: str = Form(...),
               password: str = Form(...),
               next: str = Form("/timesheet")):
    user = get_user_by_email(email.strip().lower())
    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse("login.html", {
            "request": request, "error": "Invalid email or password.", "email": email, "next": next
        }, status_code=401)

    token = create_session_token(user["id"])
    resp = RedirectResponse(next or "/timesheet", status_code=303)
    resp.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=86400 * 14)
    return resp


@router.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
