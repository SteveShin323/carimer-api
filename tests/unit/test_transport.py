"""Phase 1: header assembly, retry counts and pacing, with respx standing in for the API."""

from __future__ import annotations

import httpx
import pytest
import respx

from carimer.transport import errors
from carimer.transport.asyncio import AsyncTransport
from carimer.transport.base import CALL_COUNTER, Request, TransportOptions
from carimer.transport.sync import SyncTransport

SEARCH = "https://api.mercari.jp/v2/entities:search"
FAST = TransportOptions(min_interval=0, backoff_base=0.0, backoff_max=0.0)


@pytest.fixture(autouse=True)
def _reset_counter() -> None:
    CALL_COUNTER.reset()


def _post() -> Request:
    return Request("POST", SEARCH, json={"pageSize": 120})


# -- headers ------------------------------------------------------------------


def test_five_default_headers_are_sent() -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(SEARCH).mock(return_value=httpx.Response(200, json={"items": []}))
        with SyncTransport(FAST) as transport:
            transport.send(_post())
        headers = route.calls[0].request.headers
    assert headers["x-platform"] == "web"
    assert headers["accept"] == "application/json, text/plain, */*"
    assert headers["accept-language"] == "ja"
    assert headers["content-type"] == "application/json"
    assert headers["dpop"].count(".") == 2


def test_get_requests_omit_content_type() -> None:
    url = "https://api.mercari.jp/items/get"
    with respx.mock as mock:
        route = mock.get(url).mock(return_value=httpx.Response(200, json={"result": "OK"}))
        with SyncTransport(FAST) as transport:
            transport.send(Request("GET", url, params={"id": "m1"}))
    assert "content-type" not in route.calls[0].request.headers


def test_per_request_accept_override_replaces_the_default() -> None:
    """``master/v2/datasets/*`` needs exactly ``application/json`` or the server 406s."""
    url = "https://api.mercari.jp/master/v2/datasets/item_categories"
    with respx.mock as mock:
        route = mock.get(url).mock(return_value=httpx.Response(200, json={"itemCategories": []}))
        with SyncTransport(FAST) as transport:
            transport.send(Request("GET", url, headers={"Accept": "application/json"}))
    assert route.calls[0].request.headers["accept"] == "application/json"


def test_dpop_htu_covers_the_query_string() -> None:
    url = "https://api.mercari.jp/items/get"
    with respx.mock as mock:
        mock.get(url).mock(return_value=httpx.Response(200, json={}))
        with SyncTransport(FAST) as transport:
            request = Request("GET", url, params={"id": "m123", "include_auction": "true"})
            signed = transport.signed_url(request)
    assert signed.startswith(f"{url}?")
    assert "id=m123" in signed
    assert "include_auction=true" in signed


def test_search_session_id_is_stable_until_rotated() -> None:
    transport = SyncTransport(FAST)
    first = transport.search_session_id
    assert len(first) == 32
    assert transport.search_session_id == first
    assert transport.rotate_session() != first
    transport.close()


# -- retries ------------------------------------------------------------------


def test_403_fails_immediately_without_retry() -> None:
    with respx.mock as mock:
        route = mock.post(SEARCH).mock(return_value=httpx.Response(403, text="blocked"))
        with SyncTransport(FAST) as transport, pytest.raises(errors.BlockedError):
            transport.send(_post())
    assert route.call_count == 1
    assert CALL_COUNTER.total == 1


def test_4xx_is_not_retried() -> None:
    with respx.mock as mock:
        route = mock.post(SEARCH).mock(return_value=httpx.Response(400, json={"code": 3, "message": "x"}))
        with SyncTransport(FAST) as transport, pytest.raises(errors.BadRequestError):
            transport.send(_post())
    assert route.call_count == 1


def test_5xx_is_retried_max_retries_times_then_raises() -> None:
    with respx.mock as mock:
        route = mock.post(SEARCH).mock(return_value=httpx.Response(503, text="down"))
        with SyncTransport(FAST) as transport, pytest.raises(errors.TransportError):
            transport.send(_post())
    assert route.call_count == 4  # 1 initial + 3 retries


def test_429_is_retried_then_raises_rate_limited() -> None:
    with respx.mock as mock:
        route = mock.post(SEARCH).mock(return_value=httpx.Response(429, text="slow down"))
        with SyncTransport(FAST) as transport, pytest.raises(errors.RateLimitedError):
            transport.send(_post())
    assert route.call_count == 4


def test_retry_succeeds_after_a_transient_5xx() -> None:
    responses = [httpx.Response(500, text="x"), httpx.Response(200, json={"items": [1]})]
    with respx.mock as mock:
        mock.post(SEARCH).mock(side_effect=responses)
        with SyncTransport(FAST) as transport:
            assert transport.send(_post()) == {"items": [1]}


def test_network_errors_are_retried_then_wrapped() -> None:
    with respx.mock as mock:
        route = mock.post(SEARCH).mock(side_effect=httpx.ConnectError("no route"))
        with SyncTransport(FAST) as transport, pytest.raises(errors.TransportError, match="ConnectError"):
            transport.send(_post())
    assert route.call_count == 4


def test_non_json_2xx_body_raises_transport_error() -> None:
    with respx.mock as mock:
        mock.post(SEARCH).mock(return_value=httpx.Response(200, text="<html>nope</html>"))
        with SyncTransport(FAST) as transport, pytest.raises(errors.TransportError, match="non-JSON"):
            transport.send(_post())


def test_backoff_delay_grows_and_is_capped() -> None:
    transport = SyncTransport(TransportOptions(backoff_base=0.5, backoff_max=8.0))
    assert [transport.backoff_delay(i) for i in range(6)] == [0.5, 1.0, 2.0, 4.0, 8.0, 8.0]
    assert transport.backoff_delay(0, retry_after=3.0) == 3.0
    assert transport.backoff_delay(0, retry_after=99.0) == 8.0
    transport.close()


# -- pacing and counting ------------------------------------------------------


def test_min_interval_spaces_requests() -> None:
    with respx.mock as mock:
        mock.post(SEARCH).mock(return_value=httpx.Response(200, json={}))
        with SyncTransport(TransportOptions(min_interval=0.25)) as transport:
            import time

            start = time.monotonic()
            transport.send(_post())
            transport.send(_post())
            elapsed = time.monotonic() - start
    assert elapsed >= 0.25


def test_call_counter_records_path() -> None:
    with respx.mock as mock:
        mock.post(SEARCH).mock(return_value=httpx.Response(200, json={}))
        with SyncTransport(FAST) as transport:
            transport.send(_post())
            transport.send(_post())
    assert CALL_COUNTER.total == 2
    assert CALL_COUNTER.by_path == {"/v2/entities:search": 2}


# -- async parity -------------------------------------------------------------


async def test_async_transport_sends_the_same_headers() -> None:
    with respx.mock as mock:
        route = mock.post(SEARCH).mock(return_value=httpx.Response(200, json={"items": []}))
        async with AsyncTransport(FAST) as transport:
            assert await transport.send(_post()) == {"items": []}
        headers = route.calls[0].request.headers
    assert headers["x-platform"] == "web"
    assert "dpop" in headers


async def test_async_transport_retries_5xx_and_blocks_on_403() -> None:
    with respx.mock as mock:
        route = mock.post(SEARCH).mock(return_value=httpx.Response(502, text="bad gateway"))
        async with AsyncTransport(FAST) as transport:
            with pytest.raises(errors.TransportError):
                await transport.send(_post())
        assert route.call_count == 4

    with respx.mock as mock:
        route = mock.post(SEARCH).mock(return_value=httpx.Response(403, text="blocked"))
        async with AsyncTransport(FAST) as transport:
            with pytest.raises(errors.BlockedError):
                await transport.send(_post())
        assert route.call_count == 1


async def test_async_requests_are_serialised_by_the_lock() -> None:
    import asyncio

    in_flight = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        return httpx.Response(200, json={})

    with respx.mock as mock:
        mock.post(SEARCH).mock(side_effect=handler)
        async with AsyncTransport(FAST) as transport:
            await asyncio.gather(*(transport.send(_post()) for _ in range(4)))
    assert peak == 1
