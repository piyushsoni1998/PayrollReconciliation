"""
db.py
──────
MongoDB connection helper.

If MONGO_URI is set in the environment the tool uses MongoDB for:
  • mapping_configs   — per-client reconciliation mapping configuration
  • recon_history     — audit trail of every reconciliation run

If MONGO_URI is empty the tool falls back silently to the existing
file-based storage (no behaviour change).

Usage
─────
    from backend.api.db import get_db, mongo_enabled

    db = get_db()
    if db is not None:
        db["mapping_configs"].find_one({"client_name": "acme"})
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_client = None
_db     = None


def get_db():
    """
    Return a PyMongo Database object, or None if MongoDB is not configured.
    Connection is lazy — created on first call, reused afterwards.
    """
    global _client, _db

    if _db is not None:
        return _db

    try:
        from config.settings import MONGO_URI, MONGO_DB
    except ImportError:
        return None

    if not MONGO_URI:
        return None   # MongoDB not configured — silent fallback to files

    try:
        from pymongo import MongoClient
        from pymongo.errors import ConnectionFailure

        _client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5_000)
        # Probe the connection immediately so we fail fast
        _client.admin.command("ping")
        _db = _client[MONGO_DB]

        # ── Ensure indexes ──────────────────────────────────────────────────
        _db["mapping_configs"].create_index("client_name", unique=True)
        _db["recon_history"].create_index([("client_name", 1), ("created_at", -1)])

        logger.info("MongoDB connected — database: %s", MONGO_DB)
        return _db

    except Exception as exc:
        logger.warning(
            "MongoDB connection failed (%s). Falling back to file storage.", exc
        )
        _client = None
        _db     = None
        return None


def mongo_enabled() -> bool:
    """Return True if MongoDB is reachable."""
    return get_db() is not None
