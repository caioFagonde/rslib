from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path
from typing import Any


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


class ResponseCache:
    """WAL-backed, bounded TTL metadata cache. Each operation owns its connection."""

    def __init__(self, path: Path, ttl: float = 900, max_entries: int = 1000):
        self.path, self.ttl, self.max_entries = path, ttl, max_entries
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, expires REAL NOT NULL, payload TEXT NOT NULL)"
            )

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=15)

    def get(self, key: str) -> dict | None:
        with self.connect() as db:
            row = db.execute(
                "SELECT payload FROM responses WHERE key=? AND expires>?", (key, time.time())
            ).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key: str, value: dict) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM responses WHERE expires<?", (time.time(),))
            db.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?)",
                (key, time.time() + self.ttl, json.dumps(value)),
            )
            db.execute(
                "DELETE FROM responses WHERE key IN (SELECT key FROM responses ORDER BY expires DESC LIMIT -1 OFFSET ?)",
                (self.max_entries,),
            )
