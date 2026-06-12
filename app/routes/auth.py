"""Authentication and user management routes.

Registration bootstrap: the FIRST user to register becomes admin and
activates login enforcement for the whole app. After that, registration
stays open (users get their own isolated projects) — set
ALLOW_REGISTRATION=false to restrict new accounts to admin creation.
"""

import logging
import os

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

import db.init
from app.services.auth import (
    SESSION_COOKIE,
    any_users_exist,
    create_session_token,
    hash_password,
    login_throttled,
    resolve_request_user,
    verify_password,
)
from config import SESSION_COOKIE_SECURE, SESSION_TTL_SECONDS
from db.init import is_integrity_error

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Pragmatic email shape check (full RFC validation needs the email-validator
# package; not worth the extra dependency here).
_EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"


class RegisterRequest(BaseModel):
    email: str = Field(pattern=_EMAIL_PATTERN, max_length=254)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=256)


class LoginRequest(BaseModel):
    email: str = Field(pattern=_EMAIL_PATTERN, max_length=254)
    password: str = Field(min_length=1, max_length=256)


def _set_session(response: Response, user_id: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user_id),
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=SESSION_COOKIE_SECURE,
        path="/",
    )


def _user_payload(row) -> dict:
    return {"id": row["id"], "email": row["email"], "name": row["name"], "role": row["role"]}


@router.get("/status")
async def auth_status():
    """Whether login is enforced (any user exists) and registration is open."""
    conn = db.init.get_db()
    return {
        "auth_enabled": any_users_exist(conn),
        "registration_open": os.environ.get("ALLOW_REGISTRATION", "true").lower() != "false",
    }


@router.post("/register", status_code=201)
async def register(req: RegisterRequest, response: Response):
    conn = db.init.get_db()
    first_user = not any_users_exist(conn)
    if not first_user and os.environ.get("ALLOW_REGISTRATION", "true").lower() == "false":
        raise HTTPException(status_code=403, detail="Registration is disabled — ask an admin for an account")

    role = "admin" if first_user else "user"
    try:
        cursor = conn.execute(
            "INSERT INTO users (email, name, password_hash, role) VALUES (?, ?, ?, ?)",
            (req.email.lower(), req.name.strip(), hash_password(req.password), role),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        if is_integrity_error(exc):
            raise HTTPException(status_code=409, detail="An account with this email already exists") from exc
        raise

    user_id = cursor.lastrowid
    _set_session(response, user_id)
    if first_user:
        logger.info("First user registered — login enforcement is now ACTIVE (admin: %s)", req.email)
    row = conn.execute("SELECT id, email, name, role FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user_payload(row)


@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    if login_throttled(ip):
        raise HTTPException(status_code=429, detail="Too many login attempts — wait a minute and retry")

    conn = db.init.get_db()
    row = conn.execute(
        "SELECT id, email, name, role, password_hash FROM users WHERE email = ?",
        (req.email.lower(),),
    ).fetchone()
    # Same error for unknown email and wrong password — no account enumeration
    if row is None or not verify_password(row["password_hash"], req.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    _set_session(response, row["id"])
    return _user_payload(row)


@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"detail": "Logged out"}


@router.get("/me")
async def me(request: Request):
    conn = db.init.get_db()
    user = resolve_request_user(conn, request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}


# --- Admin: user management ----------------------------------------------------


class RoleUpdate(BaseModel):
    role: str = Field(pattern="^(admin|user)$")


def _require_admin(request: Request):
    conn = db.init.get_db()
    user = resolve_request_user(conn, request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


@router.get("/users")
async def list_users(request: Request):
    """Admin only: all accounts with their project counts."""
    _require_admin(request)
    conn = db.init.get_db()
    rows = conn.execute(
        """SELECT u.id, u.email, u.name, u.role, u.created_at,
                  COUNT(p.id) AS project_count
           FROM users u
           LEFT JOIN projects p ON p.owner_id = u.id
           GROUP BY u.id ORDER BY u.id"""
    ).fetchall()
    return [dict(r) for r in rows]


@router.patch("/users/{user_id}/role")
async def set_user_role(user_id: int, req: RoleUpdate, request: Request):
    """Admin only: promote/demote. The last admin cannot be demoted."""
    admin = _require_admin(request)
    conn = db.init.get_db()
    target = conn.execute("SELECT id, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target["role"] == "admin" and req.role == "user":
        admin_count = conn.execute(
            "SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin'"
        ).fetchone()["cnt"]
        if admin_count <= 1:
            raise HTTPException(status_code=409, detail="Cannot demote the last admin")
        if admin.id == user_id:
            logger.info("Admin %s demoted themselves", admin.email)
    conn.execute("UPDATE users SET role = ? WHERE id = ?", (req.role, user_id))
    conn.commit()
    row = conn.execute("SELECT id, email, name, role FROM users WHERE id = ?", (user_id,)).fetchone()
    return _user_payload(row)
