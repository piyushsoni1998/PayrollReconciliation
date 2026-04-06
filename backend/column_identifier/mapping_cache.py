"""
mapping_cache.py
─────────────────
Saves confirmed column-role mappings per client and file structure.

After a user confirms the mapping for a given client + file structure,
the mapping is cached to disk.  The next time the same structure is
uploaded, the cache is loaded automatically — Bedrock is not called again.

Cache key  =  client_name + file_type + MD5 hash of the column names.
This means a new column layout (even for the same client) triggers a
fresh identification pass.
"""

import hashlib
import json
import logging
from pathlib import Path
from typing import Dict, Optional

import pandas as pd

logger = logging.getLogger(__name__)


class MappingCache:
    def __init__(self, cache_dir: Path):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ── public ────────────────────────────────────────────────────────────────

    def load(
        self,
        client_name: str,
        file_type: str,
        df: pd.DataFrame,
    ) -> Optional[Dict[str, str]]:
        """
        Return cached mapping or None if no cache exists for this structure.
        Mapping format: { actual_column_name: semantic_role }
        """
        path = self._cache_path(client_name, file_type, df)
        if path.exists():
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
            logger.info("Loaded column mapping from cache: %s", path.name)
            return data
        return None

    def save(
        self,
        client_name: str,
        file_type: str,
        df: pd.DataFrame,
        mapping: Dict[str, str],
    ) -> None:
        """Persist a confirmed mapping to disk."""
        path = self._cache_path(client_name, file_type, df)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(mapping, fh, indent=2)
        logger.info("Saved column mapping to cache: %s", path.name)

    def delete(
        self,
        client_name: str,
        file_type: str,
        df: pd.DataFrame,
    ) -> None:
        """Remove a cached mapping (e.g. when the user wants to re-identify)."""
        path = self._cache_path(client_name, file_type, df)
        if path.exists():
            path.unlink()
            logger.info("Deleted column mapping cache: %s", path.name)

    def list_clients(self) -> list:
        """Return all client names that have at least one cached mapping."""
        names = set()
        for f in self.cache_dir.glob("*.json"):
            parts = f.stem.split("__")
            if parts:
                names.add(parts[0])
        return sorted(names)

    # ── private ───────────────────────────────────────────────────────────────

    def _schema_hash(self, df: pd.DataFrame) -> str:
        """MD5 of sorted column names — uniquely identifies a file structure."""
        cols_str = ",".join(sorted(str(c) for c in df.columns))
        return hashlib.md5(cols_str.encode()).hexdigest()[:10]

    def _cache_path(
        self,
        client_name: str,
        file_type: str,
        df: pd.DataFrame,
    ) -> Path:
        safe_client = "".join(c if c.isalnum() or c in "-_" else "_" for c in client_name)
        schema_hash = self._schema_hash(df)
        filename    = f"{safe_client}__{file_type}__{schema_hash}.json"
        return self.cache_dir / filename
