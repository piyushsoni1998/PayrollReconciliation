"""
auth.py
───────
Simple user authentication for the Payroll Reconciliation Tool.

Storage strategy:
  • If MongoDB is configured → users stored in the "users" collection.
  • Otherwise              → users stored in data/users.json (auto-created).

No external auth libraries required — passwords are hashed with SHA-256 + salt,
tokens are UUID4 strings stored alongside the user record.
"""

import hashlib, os, uuid, json, logging
from datetime import datetime, timezone
from pathlib   import Path

from fastapi           import APIRouter
from fastapi.responses import JSONResponse
from fastapi           import HTTPException
from pydantic          import BaseModel

from backend.api.db import get_db

logger = logging.getLogger(__name__)
router = APIRouter()

# ── File-based fallback path ──────────────────────────────────────────────
_DATA_DIR   = Path(__file__).resolve().parents[4] / "data"
_USERS_FILE = _DATA_DIR / "users.json"


def _hash_password(password: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}{password}".encode()).hexdigest()


def _gen_salt() -> str:
    return uuid.uuid4().hex


def _gen_token() -> str:
    return uuid.uuid4().hex


# ── File-based user store ─────────────────────────────────────────────────
def _load_file_users() -> dict:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _USERS_FILE.exists():
        return {}
    try:
        return json.loads(_USERS_FILE.read_text())
    except Exception:
        return {}


def _save_file_users(users: dict):
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _USERS_FILE.write_text(json.dumps(users, indent=2))


# ── User lookup helpers ───────────────────────────────────────────────────
def _find_user_by_username(username: str):
    """Return user dict or None."""
    db = get_db()
    if db is not None:
        return db["users"].find_one({"username": username.lower()})
    users = _load_file_users()
    return users.get(username.lower())


def _find_user_by_token(token: str):
    """Return user dict or None."""
    db = get_db()
    if db is not None:
        return db["users"].find_one({"token": token})
    users = _load_file_users()
    for u in users.values():
        if u.get("token") == token:
            return u
    return None


def _find_user_by_id(user_id: str):
    db = get_db()
    if db is not None:
        return db["users"].find_one({"user_id": user_id})
    users = _load_file_users()
    for u in users.values():
        if u.get("user_id") == user_id:
            return u
    return None


def _save_user(user: dict):
    db = get_db()
    if db is not None:
        db["users"].update_one(
            {"user_id": user["user_id"]},
            {"$set": user},
            upsert=True,
        )
    else:
        users = _load_file_users()
        users[user["username"]] = user
        _save_file_users(users)


# ── Pydantic models ───────────────────────────────────────────────────────
class RegisterRequest(BaseModel):
    username:     str
    password:     str
    display_name: str = ""


class LoginRequest(BaseModel):
    username: str
    password: str


# ── Routes ────────────────────────────────────────────────────────────────
@router.post("/auth/register")
async def register(req: RegisterRequest):
    username = req.username.strip().lower()
    if not username or not req.password:
        raise HTTPException(400, "Username and password are required.")
    if len(req.password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters.")

    if _find_user_by_username(username):
        raise HTTPException(409, "Username already exists.")

    salt  = _gen_salt()
    token = _gen_token()
    user  = {
        "user_id":      uuid.uuid4().hex,
        "username":     username,
        "display_name": (req.display_name.strip() or username),
        "salt":         salt,
        "password_hash": _hash_password(req.password, salt),
        "token":        token,
        "created_at":   datetime.now(timezone.utc).isoformat(),
    }
    _save_user(user)
    logger.info("New user registered: %s", username)
    return JSONResponse({
        "ok":           True,
        "user_id":      user["user_id"],
        "username":     user["username"],
        "display_name": user["display_name"],
        "token":        token,
    })


@router.post("/auth/login")
async def login(req: LoginRequest):
    username = req.username.strip().lower()
    user = _find_user_by_username(username)
    if not user:
        raise HTTPException(401, "Invalid username or password.")

    expected = _hash_password(req.password, user["salt"])
    if expected != user["password_hash"]:
        raise HTTPException(401, "Invalid username or password.")

    # Rotate token on each login
    token = _gen_token()
    user["token"] = token
    _save_user(user)

    return JSONResponse({
        "ok":           True,
        "user_id":      user["user_id"],
        "username":     user["username"],
        "display_name": user.get("display_name", user["username"]),
        "token":        token,
    })


@router.get("/auth/verify")
async def verify(token: str = ""):
    if not token:
        raise HTTPException(401, "No token provided.")
    user = _find_user_by_token(token)
    if not user:
        raise HTTPException(401, "Token invalid or expired.")
    return JSONResponse({
        "ok":           True,
        "user_id":      user["user_id"],
        "username":     user["username"],
        "display_name": user.get("display_name", user["username"]),
    })
