"""
core/auth.py
Session management, magic-link tokens, dependency injection for FastAPI routes.
In production: swap in-memory dicts for Redis + a real DB.
"""
import uuid, hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict
from fastapi import HTTPException, Header

from core.config import settings

# ── In-memory stores (swap for Redis + Postgres in production) ────────────────
SESSIONS: Dict[str, dict] = {}       # bearer_token → user dict
MAGIC_TOKENS: Dict[str, dict] = {}   # magic_token  → {email, expires_at}


def _user_id(email: str) -> str:
    """Deterministic user ID from email."""
    return hashlib.md5(email.lower().encode()).hexdigest()[:16]


def create_session(email: str, name: str = "", company: str = "", **extra) -> str:
    """Create a new session and return the bearer token."""
    token = str(uuid.uuid4())
    uid = _user_id(email)
    SESSIONS[token] = {
        "token": token,
        "user_id": uid,
        "email": email,
        "name": name or email.split("@")[0].replace(".", " ").title(),
        "company": company,
        "created_at": datetime.utcnow().isoformat(),
        "expires_at": (datetime.utcnow() + timedelta(hours=settings.session_ttl_hours)).isoformat(),
        **extra
    }
    return token


def create_magic_token(email: str) -> str:
    """Create a single-use magic link token (15-minute TTL)."""
    token = str(uuid.uuid4())
    MAGIC_TOKENS[token] = {
        "email": email,
        "expires_at": (datetime.utcnow() + timedelta(minutes=15)).isoformat()
    }
    return token


def consume_magic_token(token: str) -> Optional[str]:
    """Validate and consume a magic token. Returns email or None."""
    entry = MAGIC_TOKENS.pop(token, None)
    if not entry:
        return None
    if datetime.fromisoformat(entry["expires_at"]) < datetime.utcnow():
        return None   # expired
    return entry["email"]


def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    """FastAPI dependency — validates Bearer token, returns user dict."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    user = SESSIONS.get(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or not found. Please log in again.")
    # Check TTL
    if "expires_at" in user:
        if datetime.fromisoformat(user["expires_at"]) < datetime.utcnow():
            SESSIONS.pop(token, None)
            raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
    return user


def invalidate_session(token: str) -> None:
    SESSIONS.pop(token, None)


def active_session_count() -> int:
    return len(SESSIONS)
