"""Phase 2: the client facade wires query → body → model (respx-mocked)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import respx

from carimer import AsyncClient, Client, SearchQuery, Sort, TransportOptions
from carimer.api.search import SEARCH_URL

FAST = TransportOptions(min_interval=0)


def _response(payload: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json=payload)


def _page(items: list[str], next_token: str = "") -> dict[str, Any]:
    return {
        "meta": {"nextPageToken": next_token, "numFound": "2472"},
        "items": [{"id": i, "name": i, "price": "1000", "itemType": "ITEM_TYPE_MERCARI"} for i in items],
    }


def test_search_sends_the_built_body_and_parses_the_page() -> None:
    with respx.mock as mock:
        route = mock.post(SEARCH_URL).mock(return_value=_response(_page(["m1", "m2"], "v1:1")))
        with Client(options=FAST) as client:
            page = client.search(SearchQuery("iphone 15").price(10_000, 80_000))
            session_id = client.transport.search_session_id
            device_uuid = client.transport.device_uuid
    body = json.loads(route.calls[0].request.content)
    assert body["searchCondition"]["keyword"] == "iphone 15"
    assert body["searchCondition"]["priceMin"] == 10_000
    assert body["searchSessionId"] == session_id
    assert body["laplaceDeviceUuid"] == device_uuid
    assert [item.id for item in page.items] == ["m1", "m2"]
    assert page.approx_total == 2472


def test_search_accepts_a_bare_keyword() -> None:
    with respx.mock as mock:
        route = mock.post(SEARCH_URL).mock(return_value=_response(_page(["m1"])))
        with Client(options=FAST) as client:
            client.search("ポケモンカード")
    assert json.loads(route.calls[0].request.content)["searchCondition"]["keyword"] == "ポケモンカード"


def test_page_token_and_size_reach_the_body() -> None:
    with respx.mock as mock:
        route = mock.post(SEARCH_URL).mock(return_value=_response(_page(["m1"])))
        with Client(options=FAST) as client:
            client.search("x", page_token="v1:2", page_size=30)
    body = json.loads(route.calls[0].request.content)
    assert body["pageToken"] == "v1:2"
    assert body["pageSize"] == 30


def test_iter_pages_walks_and_reuses_one_session_id() -> None:
    pages = [_response(_page(["m1"], "v1:1")), _response(_page(["m2"], ""))]
    with respx.mock as mock:
        route = mock.post(SEARCH_URL).mock(side_effect=pages)
        with Client(options=FAST) as client:
            collected = list(client.iter_pages("x"))
    assert [p.items[0].id for p in collected] == ["m1", "m2"]
    bodies = [json.loads(call.request.content) for call in route.calls]
    assert bodies[1]["pageToken"] == "v1:1"
    assert len({body["searchSessionId"] for body in bodies}) == 1


def test_iter_items_flattens_and_deduplicates() -> None:
    pages = [_response(_page(["m1", "m2"], "v1:1")), _response(_page(["m2", "m3"], ""))]
    with respx.mock as mock:
        mock.post(SEARCH_URL).mock(side_effect=pages)
        with Client(options=FAST) as client:
            assert [i.id for i in client.iter_items("x")] == ["m1", "m2", "m3"]


def test_sort_is_serialised() -> None:
    with respx.mock as mock:
        route = mock.post(SEARCH_URL).mock(return_value=_response(_page(["m1"])))
        with Client(options=FAST) as client:
            client.search(SearchQuery("x").sort(Sort.PRICE))
    assert json.loads(route.calls[0].request.content)["searchCondition"]["sort"] == "SORT_PRICE"


async def test_async_client_parity() -> None:
    pages = [_response(_page(["m1"], "v1:1")), _response(_page(["m2"], ""))]
    with respx.mock as mock:
        mock.post(SEARCH_URL).mock(side_effect=pages)
        async with AsyncClient(options=FAST) as client:
            ids = [item.id async for item in client.iter_items("x")]
    assert ids == ["m1", "m2"]


def test_client_forwards_the_query_thumbnail_type() -> None:
    from carimer import ThumbnailType

    with respx.mock as mock:
        route = mock.post(SEARCH_URL).mock(return_value=_response(_page(["m1"])))
        with Client(options=FAST) as client:
            client.search(SearchQuery("x").thumbnail_type(ThumbnailType.JPEG))
    assert json.loads(route.calls[0].request.content)["thumbnailTypes"] == ["JPEG"]


async def test_async_client_forwards_the_query_thumbnail_type() -> None:
    from carimer import ThumbnailType

    with respx.mock as mock:
        route = mock.post(SEARCH_URL).mock(return_value=_response(_page(["m1"])))
        async with AsyncClient(options=FAST) as client:
            await client.search(SearchQuery("x").thumbnail_type(ThumbnailType.WEBP))
    assert json.loads(route.calls[0].request.content)["thumbnailTypes"] == ["WEBP"]
