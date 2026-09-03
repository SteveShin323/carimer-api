"""Header assembly, signing, retry policy and the live-call counter. No I/O here.

Everything in this module is either a pure function or in-memory bookkeeping, so the
sync and async transports (``sync.py`` / ``asyncio.py``) share the whole decision layer
and differ only in how they await.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import isfinite
from typing import Any, Final

import httpx

from carimer.transport import errors
from carimer.transport.dpop import DpopSigner

__all__ = [
    "BASE_URL",
    "CALL_COUNTER",
    "CallCounter",
    "Request",
    "TransportCore",
    "TransportOptions",
    "json_body",
    "retry_after_seconds",
]

BASE_URL: Final = "https://api.mercari.jp"

# The five headers the web app sends (01 §1.1). `Content-Type` is added for POST only.
_ACCEPT: Final = "application/json, text/plain, */*"
_ACCEPT_LANGUAGE: Final = "ja"
_PLATFORM: Final = "web"
_DEFAULT_UA: Final = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class CallCounter:
    """Counts requests actually put on the wire, for the live-call budget."""

    def __init__(self) -> None:
        self.total = 0
        self.by_path: dict[str, int] = {}

    def record(self, url: str) -> None:
        self.total += 1
        path = url.removeprefix(BASE_URL).split("?", 1)[0]
        self.by_path[path] = self.by_path.get(path, 0) + 1

    def reset(self) -> None:
        self.total = 0
        self.by_path.clear()


#: Process-wide counter. ``tests/conftest.py`` reports it per pytest session.
CALL_COUNTER: Final = CallCounter()


@dataclass(frozen=True, slots=True)
class Request:
    """What an ``api/`` builder returns: everything needed to send, nothing more."""

    method: str
    url: str
    params: dict[str, Any] | None = None
    json: dict[str, Any] | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TransportOptions:
    """Knobs shared by both transports.

    ``min_interval`` and concurrency 1 are deliberate: the block threshold is unknown
    (01 §1.4), so the default is polite.
    """

    user_agent: str | None = _DEFAULT_UA
    device_uuid: str | None = None
    rotate_every: int = 0
    min_interval: float = 0.5
    timeout: float = 30.0
    max_retries: int = 3
    proxy: str | None = None
    backoff_base: float = 0.5
    backoff_max: float = 8.0
    max_retry_after: float | None = 3600.0


class TransportCore:
    """Signing, header assembly and retry decisions. Holds no HTTP client."""

    def __init__(self, options: TransportOptions | None = None) -> None:
        self.options = options or TransportOptions()
        self._signer = DpopSigner(
            device_uuid=self.options.device_uuid,
            rotate_every=self.options.rotate_every,
        )
        self._search_session_id = _new_session_id()
        self._device_uuid = self.options.device_uuid or str(uuid.uuid4())

    @property
    def signer(self) -> DpopSigner:
        return self._signer

    @property
    def search_session_id(self) -> str:
        """32-char hex, created once per transport and shared by search and facets."""
        return self._search_session_id

    def rotate_session(self) -> str:
        self._search_session_id = _new_session_id()
        return self._search_session_id

    @property
    def device_uuid(self) -> str:
        """Stable per client, like the web app's ``laplaceDeviceUuid``."""
        return self._device_uuid

    def headers_for(self, request: Request) -> dict[str, str]:
        """Base headers + the DPoP signature, with per-request overrides applied last.

        ``master/v2/datasets/*`` passes ``Accept: application/json``, which must replace
        the default value exactly or the server answers 406 (01 §9).
        """
        headers = {
            "Accept": _ACCEPT,
            "Accept-Language": _ACCEPT_LANGUAGE,
            "X-Platform": _PLATFORM,
        }
        if self.options.user_agent:
            headers["User-Agent"] = self.options.user_agent
        if request.method.upper() == "POST":
            headers["Content-Type"] = "application/json"
        headers.update(request.headers)
        headers["DPoP"] = self._signer.sign(request.method, self.signed_url(request))
        return headers

    def signed_url(self, request: Request) -> str:
        """The full URL including the query string, exactly as the web app signs it."""
        if not request.params:
            return request.url
        import urllib.parse

        query = urllib.parse.urlencode({k: v for k, v in request.params.items() if v is not None}, doseq=True)
        return f"{request.url}?{query}" if query else request.url

    # -- retry policy ---------------------------------------------------------

    def should_retry(self, status: int, attempt: int) -> bool:
        """429 / 5xx only, and only while attempts remain (01 §1.4).

        403 is treated as a block and fails immediately; every other 4xx is a client
        bug that a retry cannot fix.
        """
        return attempt < self.options.max_retries and errors.is_retryable_status(status)

    def backoff_delay(self, attempt: int, retry_after: float | None = None) -> float:
        if retry_after is not None and retry_after >= 0:
            return retry_after
        return min(self.options.backoff_base * 2.0**attempt, self.options.backoff_max)

    def retry_after_exceeds_limit(self, retry_after: float | None) -> bool:
        limit = self.options.max_retry_after
        return retry_after is not None and limit is not None and retry_after > limit

    def error_for(self, status: int, headers: dict[str, str] | None, body: bytes) -> errors.CarimerError:
        return errors.from_response(status, headers, body)


def _new_session_id() -> str:
    return secrets.token_hex(16)


def retry_after_seconds(response: httpx.Response, *, now: datetime | None = None) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            return None
        current = now or datetime.now(UTC)
        return max(0.0, (retry_at - current).total_seconds())
    if not isfinite(seconds) or seconds < 0:
        return None
    return seconds


def json_body(response: httpx.Response) -> dict[str, Any]:
    """Parse a 2xx body. Non-object JSON is wrapped so callers always see a dict."""
    try:
        parsed = response.json()
    except ValueError as exc:
        raise errors.TransportError(
            f"non-JSON response body: {response.text[:200]!r}",
            status=response.status_code,
            body=response.content,
        ) from exc
    if isinstance(parsed, dict):
        return parsed
    return {"_root": parsed}
