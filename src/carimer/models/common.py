"""Model base class and the lenient coercion helpers (03 §1.3).

The search API returns every number as a string (``"price": "81999"``) while the detail
API returns real numbers, and timestamps arrive as unix seconds in one place and ISO
strings in another. These helpers absorb both and return ``None`` rather than raising,
because only ``id``/``name``/``price`` are required fields.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["RawModel", "to_bool", "to_datetime", "to_int", "to_str", "to_str_list"]


class RawModel(BaseModel):
    """Base for every response model: keeps the untouched payload in ``raw``.

    New API fields therefore never get lost, even before the model learns about them.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    raw: dict[str, Any] = Field(default_factory=dict, repr=False)


def to_int(value: object) -> int | None:
    """``"81999"`` / ``81999`` / ``81999.0`` → ``81999``; anything else → ``None``."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            try:
                return int(float(text))
            except ValueError:
                return None
    return None


def to_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value or None
    return str(value)


def to_str_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list | tuple):
        return [str(v) for v in value if v is not None]
    return []


def to_bool(value: object) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0", ""}:
            return False
    if isinstance(value, int):
        return bool(value)
    return None


def to_datetime(value: object) -> datetime | None:
    """Unix seconds (int or string) or an ISO 8601 string → UTC-aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return _from_unix(int(value))
    if isinstance(value, str):
        text = value.strip()
        if not text or text == "0":
            return None
        if text.lstrip("-").isdigit():
            return _from_unix(int(text))
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _from_unix(seconds: int) -> datetime | None:
    if seconds <= 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
