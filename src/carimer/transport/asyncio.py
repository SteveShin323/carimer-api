"""Async transport: ``httpx.AsyncClient`` + a lock that also enforces ``min_interval``.

The lock serialises requests (concurrency 1 by design, 03 §6) and doubles as the
critical section for the pacing clock.
"""

from __future__ import annotations

import asyncio
import time
from types import TracebackType
from typing import Any

import httpx

from carimer.transport import errors
from carimer.transport.base import (
    CALL_COUNTER,
    Request,
    TransportCore,
    TransportOptions,
    json_body,
    retry_after_seconds,
)

__all__ = ["AsyncTransport"]


class AsyncTransport(TransportCore):
    """Same decisions as :class:`~carimer.transport.sync.SyncTransport`, awaited."""

    def __init__(
        self,
        options: TransportOptions | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(options)
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=self.options.timeout,
            proxy=self.options.proxy,
            follow_redirects=True,
        )
        self._lock = asyncio.Lock()
        self._last_sent: float | None = None

    async def __aenter__(self) -> AsyncTransport:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def send(self, request: Request) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                response = await self._send_once(request)
            except httpx.HTTPError as exc:
                if attempt >= self.options.max_retries:
                    raise errors.TransportError(f"{type(exc).__name__}: {exc}") from exc
                await asyncio.sleep(self.backoff_delay(attempt))
                attempt += 1
                continue
            if response.status_code >= 400:
                if self.should_retry(response.status_code, attempt):
                    await asyncio.sleep(self.backoff_delay(attempt, retry_after_seconds(response)))
                    attempt += 1
                    continue
                raise self.error_for(response.status_code, dict(response.headers), response.content)
            return json_body(response)

    async def _send_once(self, request: Request) -> httpx.Response:
        """One attempt. The lock keeps concurrency at 1 and guards the pacing clock."""
        async with self._lock:
            await self._wait_for_slot()
            response = await self._client.request(
                request.method,
                request.url,
                params=request.params,
                json=request.json,
                headers=self.headers_for(request),
            )
        CALL_COUNTER.record(str(response.request.url))
        return response

    async def _wait_for_slot(self) -> None:
        interval = self.options.min_interval
        if interval <= 0:
            return
        if self._last_sent is not None:
            remaining = interval - (time.monotonic() - self._last_sent)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last_sent = time.monotonic()
