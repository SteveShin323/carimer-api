"""In-memory TTL cache with an optional JSON disk layer (03 §3.8).

Facet definitions and master data change rarely, so a 24 h memory cache removes almost
all repeat traffic. The disk layer is off unless ``cache_dir`` is given.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import time
from typing import Any

__all__ = ["DEFAULT_TTL_SECONDS", "TTLCache"]

DEFAULT_TTL_SECONDS = 24 * 60 * 60


class TTLCache:
    """Keys are strings; values are anything JSON-serialisable."""

    def __init__(
        self,
        *,
        ttl: float = DEFAULT_TTL_SECONDS,
        cache_dir: str | pathlib.Path | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        self.ttl = ttl
        self._clock = clock
        self._entries: dict[str, tuple[float, Any]] = {}
        self._dir = pathlib.Path(cache_dir) if cache_dir else None
        if self._dir is not None:
            self._dir.mkdir(parents=True, exist_ok=True)

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is not None:
            stored_at, value = entry
            if self._clock() - stored_at < self.ttl:
                return value
            del self._entries[key]
        return self._read_disk(key)

    def set(self, key: str, value: Any) -> None:
        self._entries[key] = (self._clock(), value)
        self._write_disk(key, value)

    def clear(self) -> None:
        self._entries.clear()

    # -- optional disk layer --------------------------------------------------

    def _path(self, key: str) -> pathlib.Path | None:
        if self._dir is None:
            return None
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        return self._dir / f"{digest}.json"

    def _read_disk(self, key: str) -> Any | None:
        path = self._path(key)
        if path is None or not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        stored_at = payload.get("stored_at")
        if not isinstance(stored_at, int | float) or time.time() - stored_at >= self.ttl:
            return None
        value = payload.get("value")
        self._entries[key] = (self._clock(), value)
        return value

    def _write_disk(self, key: str, value: Any) -> None:
        path = self._path(key)
        if path is None:
            return
        try:
            path.write_text(
                json.dumps({"stored_at": time.time(), "value": value}, ensure_ascii=False),
                encoding="utf-8",
            )
        except (OSError, TypeError, ValueError):
            # A cache is a convenience: an unwritable directory must not break a call.
            return
