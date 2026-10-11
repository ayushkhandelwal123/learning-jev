"""NEW in Level 5: a persistent cache plus "single-flight" de-duplication.

Why cache?  Asking Jev or the LLM the same thing twice costs money and time.
  * Re-running after a crash resumes where it stopped (finished posts are cached).
  * Re-processing the same post (a repost, an edit-and-revert) is free.
  * Changing thresholds is free, because signals do not depend on thresholds.

Why single-flight?  Without it, 10 identical posts arriving at the same moment
all miss the cache together and make 10 API calls (a "cache stampede").
With it, one call is made and the other nine wait for its answer.
"""

import asyncio
import hashlib
import json
import sqlite3
import time
from collections import Counter
from pathlib import Path


def make_key(*parts: str) -> str:
    """Stable fingerprint of everything that affects an answer.

    If ANY part changes (the post text, the questions, the model, the prompt), the
    key changes and the old cached answer is simply never found. That is how stale
    answers are avoided without manual cache clearing.
    """
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


class DiskCache:
    """Tiny key-value store on SQLite (in the Python standard library)."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS entries ("
            "namespace TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
            "created_at REAL NOT NULL, PRIMARY KEY (namespace, key))"
        )
        self._db.commit()

    def get(self, namespace: str, key: str) -> dict | None:
        row = self._db.execute(
            "SELECT value FROM entries WHERE namespace = ? AND key = ?", (namespace, key)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, namespace: str, key: str, value: dict) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?)",
            (namespace, key, json.dumps(value), time.time()),
        )
        self._db.commit()  # commit every time, so a crash loses nothing

    def count(self, namespace: str) -> int:
        return self._db.execute(
            "SELECT COUNT(*) FROM entries WHERE namespace = ?", (namespace,)
        ).fetchone()[0]

    def close(self) -> None:
        self._db.close()


class NullCache:
    """A cache that never remembers anything (used by --no-cache)."""

    def get(self, namespace: str, key: str) -> dict | None:
        return None

    def set(self, namespace: str, key: str, value: dict) -> None:
        pass

    def count(self, namespace: str) -> int:
        return 0

    def close(self) -> None:
        pass


class CachedCaller:
    """Look in the cache first, join an identical call already in flight, or call."""

    def __init__(self, cache, dedupe: bool = True) -> None:
        self.cache = cache
        self.dedupe = dedupe
        self._inflight: dict[tuple[str, str], asyncio.Future] = {}
        self.sources: Counter = Counter()  # (namespace, source) -> count

    async def get(self, namespace: str, key: str, fetch) -> tuple[dict, str]:
        """Return (value, source). Source is "cache", "deduped" or "api".

        `fetch` is an async function that makes the real call. Failures are never
        cached: the exception reaches every caller waiting on that call.
        """
        hit = self.cache.get(namespace, key)
        if hit is not None:
            self.sources[(namespace, "cache")] += 1
            return hit, "cache"

        slot = (namespace, key)
        if self.dedupe and slot in self._inflight:
            value = await self._inflight[slot]  # wait for the call already running
            self.sources[(namespace, "deduped")] += 1
            return value, "deduped"

        task = asyncio.ensure_future(fetch())
        if self.dedupe:
            self._inflight[slot] = task
        try:
            value = await task
        finally:
            self._inflight.pop(slot, None)
        self.cache.set(namespace, key, value)
        self.sources[(namespace, "api")] += 1
        return value, "api"
