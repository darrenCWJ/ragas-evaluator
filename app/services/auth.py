"""User authentication and project access control.

Design:
- argon2id password hashing (argon2-cffi)
- Signed, time-limited session cookies (itsdangerous) — no server-side
  session table; logout clears the cookie, TTL bounds exposure
- The FIRST registered user becomes admin (bootstrap); admins can promote
- Open mode: until any user exists, the app behaves exactly as before
  (optionally gated by the legacy RAGAS_API_KEY bearer token)
- RAGAS_API_KEY remains a machine token and is treated as an admin
  identity so CI gates and scripts keep working
- Admins can access every project; other users need ownership or membership
"""

import logging
import secrets
import threading
import time
from dataclasses import dataclass

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from config import LOGIN_RATE_LIMIT, SESSION_SECRET, SESSION_TTL_SECONDS

logger = logging.getLogger(__name__)

SESSION_COOKIE = "tribunal_session"

_hasher = PasswordHasher()  # argon2id defaults

if SESSION_SECRET:
    _secret = SESSION_SECRET
else:
    _secret = secrets.token_hex(32)
    logger.warning(
        "SESSION_SECRET is not set — using a random per-process secret. "
        "All logins will be invalidated on restart. Set SESSION_SECRET in .env."
    )
_serializer = URLSafeTimedSerializer(_secret, salt="tribunal-session")


@dataclass(frozen=True)
class CurrentUser:
    id: int | None  # None for the machine token identity
    email: str
    name: str
    role: str  # "admin" | "user"

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


MACHINE_USER = CurrentUser(id=None, email="api@machine", name="API token", role="admin")


# --- Password hashing -------------------------------------------------------


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
        return True
    except VerifyMismatchError:
        return False
    except Exception:
        logger.warning("Password verification failed unexpectedly", exc_info=True)
        return False


# --- Session cookies ----------------------------------------------------------


def create_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str) -> int | None:
    """Return the user id for a valid, unexpired session token; else None."""
    try:
        data = _serializer.loads(token, max_age=SESSION_TTL_SECONDS)
        uid = data.get("uid")
        return uid if isinstance(uid, int) else None
    except (BadSignature, SignatureExpired):
        return None
    except Exception:
        return None


# --- User store ----------------------------------------------------------------


def any_users_exist(conn) -> bool:
    return conn.execute("SELECT id FROM users LIMIT 1").fetchone() is not None


def get_user(conn, user_id: int) -> CurrentUser | None:
    row = conn.execute(
        "SELECT id, email, name, role FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    if row is None:
        return None
    return CurrentUser(id=row["id"], email=row["email"], name=row["name"], role=row["role"])


def resolve_request_user(conn, request) -> CurrentUser | None:
    """Identify the caller: session cookie, machine bearer token, or None."""
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        uid = read_session_token(token)
        if uid is not None:
            user = get_user(conn, uid)
            if user is not None:
                return user

    import os

    machine_key = os.environ.get("RAGAS_API_KEY", "")
    if machine_key:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer ") and secrets.compare_digest(
            auth[len("Bearer "):], machine_key
        ):
            return MACHINE_USER
    return None


# --- Project access -------------------------------------------------------------


def user_can_access_project(conn, user: CurrentUser, project_id: int) -> bool:
    """Owner, member, or admin. Legacy ownerless projects stay admin-only
    once auth is active — an admin assigns them via the members endpoint."""
    if user.is_admin:
        return True
    if user.id is None:
        return False
    row = conn.execute(
        """SELECT 1 FROM projects p
           LEFT JOIN project_members pm
                  ON pm.project_id = p.id AND pm.user_id = ?
           WHERE p.id = ? AND (p.owner_id = ? OR pm.user_id IS NOT NULL)""",
        (user.id, project_id, user.id),
    ).fetchone()
    return row is not None


# --- Login rate limiting (in-memory, per IP) --------------------------------------

_attempts_lock = threading.Lock()
_attempts: dict[str, list[float]] = {}


def login_throttled(ip: str) -> bool:
    """True when this IP exceeded LOGIN_RATE_LIMIT attempts in the last minute."""
    now = time.monotonic()
    with _attempts_lock:
        window = [t for t in _attempts.get(ip, []) if now - t < 60.0]
        throttled = len(window) >= LOGIN_RATE_LIMIT
        if not throttled:
            window.append(now)
        _attempts[ip] = window
        # Bound the registry so it can't grow without limit
        if len(_attempts) > 10_000:
            _attempts.clear()
    return throttled
