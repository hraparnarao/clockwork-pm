"""
ClockWork PM – authentication helpers.
Session via signed cookies (itsdangerous).
"""
import os
import bcrypt as _bcrypt
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app.database import get_db

SECRET_KEY = os.environ.get("CLOCKWORK_SECRET", "change-me-in-production-clockwork")
SESSION_COOKIE = "cw_session"
_s = URLSafeTimedSerializer(SECRET_KEY)


def hash_password(plain: str) -> str:
    return _bcrypt.hashpw(plain.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def create_session_token(user_id: int) -> str:
    return _s.dumps({"uid": user_id})


def decode_session_token(token: str, max_age: int = 86400 * 14):
    try:
        data = _s.loads(token, max_age=max_age)
        return data.get("uid")
    except (BadSignature, SignatureExpired):
        return None


def get_user_by_email(email: str):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email=? AND is_active=1", (email,)).fetchone()
    conn.close()
    return row


def get_user_by_id(user_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()
    return row
