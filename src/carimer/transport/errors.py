"""Exception hierarchy and response → exception mapping (01-api-spec.md §1.3).

The API answers with two unrelated error shapes plus a couple of non-JSON bodies:

* legacy REST  ``{"result": "error", "errors": [{"code": "...", "message": "..."}]}``
* gRPC gateway ``{"code": 3, "message": "...", "requestId": "..."}``
* plain text    ``no accepted candidate variant`` (406), ``404 page not found``

``from_response`` is a pure function so the sync and async transports share it.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = [
    "AuthError",
    "BadRequestError",
    "BlockedError",
    "CarimerError",
    "NotAcceptableError",
    "NotFoundError",
    "ParseError",
    "RateLimitedError",
    "ShopsItemError",
    "TransportError",
    "UnknownFacetValue",
    "from_response",
    "is_retryable_status",
    "parse_error_body",
]


class CarimerError(Exception):
    """Base class for every error this package raises."""


class TransportError(CarimerError):
    """Network failure or a 5xx that survived the retries."""

    def __init__(self, message: str, *, status: int | None = None, body: bytes | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class AuthError(CarimerError):
    """401 — DPoP header missing or its ``htu``/``htm`` do not match the request."""


class BlockedError(CarimerError):
    """403 — suspected Cloudflare block. Never retried (01 §1.4)."""


class BadRequestError(CarimerError):
    """400 — bad enum, wrong JSON type, ``InvalidArgument``, ``UnsupportedVersionException``…"""

    def __init__(self, code: str | int | None, message: str) -> None:
        super().__init__(f"{code}: {message}" if code is not None else message)
        self.code = code
        self.message = message


class NotFoundError(CarimerError):
    """404 — item / user / shops product / master dataset / unknown path."""

    def __init__(self, kind: str, message: str = "") -> None:
        super().__init__(f"{kind}: {message}" if message else kind)
        self.kind = kind
        self.message = message


class RateLimitedError(CarimerError):
    """429 — body shape unobserved, so the mapping is by status code alone."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__(f"rate limited (retry_after={retry_after})")
        self.retry_after = retry_after


class NotAcceptableError(CarimerError):
    """406 — ``master/v2/datasets/*`` requires exactly ``Accept: application/json`` (01 §9)."""


class ShopsItemError(CarimerError):
    """A Mercari Shops product id was passed to ``get_item``.

    Raised client-side *before* any request: the server's 400 for this case is
    indistinguishable from a malformed id (01 §5).
    """


class ParseError(CarimerError):
    """A required response field (id / name / price) is missing."""

    def __init__(self, field: str, raw: Any) -> None:
        super().__init__(f"missing or unparseable required field {field!r}")
        self.field = field
        self.raw = raw


class UnknownFacetValue(CarimerError):
    """A facet display name could not be resolved to a UUID (live, cache or fallback)."""


_NOT_FOUND_CODES = frozenset(
    {"RecordNotFoundException", "UserNotFoundException", "NotFoundException", "ItemNotFoundException"}
)


def parse_error_body(body: bytes | str | None) -> tuple[str | int | None, str]:
    """Return ``(code, message)`` for any of the observed error shapes.

    Non-JSON bodies (406 text, ``404 page not found``) come back as ``(None, text[:200])``.
    """
    if body is None:
        return None, ""
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else body
    try:
        parsed = json.loads(text)
    except (ValueError, UnicodeDecodeError):
        return None, text.strip()[:200]
    if not isinstance(parsed, dict):
        return None, text.strip()[:200]
    errors = parsed.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            code = first.get("code")
            return (code if isinstance(code, str | int) else None), str(first.get("message", ""))
    if "code" in parsed or "message" in parsed:
        code = parsed.get("code")
        return (code if isinstance(code, str | int) else None), str(parsed.get("message", ""))
    return None, text.strip()[:200]


def is_retryable_status(status: int) -> bool:
    """429 and 5xx are retried; every other 4xx (403 included) is not (01 §1.4)."""
    return status == 429 or 500 <= status <= 599


def _retry_after(headers: dict[str, str] | None) -> float | None:
    if not headers:
        return None
    raw = next((v for k, v in headers.items() if k.lower() == "retry-after"), None)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _not_found_kind(code: str | int | None, message: str) -> str:
    if isinstance(code, str) and code in _NOT_FOUND_CODES:
        return code
    if code == 5:
        return "NotFound"
    if "page not found" in message:
        return "UnknownPath"
    return "NotFound"


def from_response(status: int, headers: dict[str, str] | None, body: bytes | str | None) -> CarimerError:
    """Map an HTTP error response onto the exception hierarchy (03 §3.2)."""
    code, message = parse_error_body(body)
    if status == 400:
        return BadRequestError(code, message)
    if status == 401:
        return AuthError(message or "unauthorized")
    if status == 403:
        return BlockedError(message or "forbidden (suspected block)")
    if status == 404:
        return NotFoundError(_not_found_kind(code, message), message)
    if status == 406:
        return NotAcceptableError(message or "not acceptable")
    if status == 429:
        return RateLimitedError(_retry_after(headers))
    raw = body.encode() if isinstance(body, str) else body
    return TransportError(message or f"HTTP {status}", status=status, body=raw)
