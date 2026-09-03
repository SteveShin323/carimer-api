"""`relateditems/component` and its loadmore walk (01 §8.4)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import respx

from carimer import Client, RelatedComponentType, TransportOptions
from carimer.models.misc import RelatedComponent
from carimer.transport.base import BASE_URL

FAST = TransportOptions(min_interval=0)
COMPONENT_URL = f"{BASE_URL}/v2/relateditems/component"
LOADMORE_URL = f"{BASE_URL}/v2/relateditems/loadmore"


def test_parsing(related_component_payload: dict[str, Any]) -> None:
    component = RelatedComponent.from_api(related_component_payload)
    assert component.title
    assert component.component_type == related_component_payload["componentType"]
    assert component.items
    assert all(item.id and item.price >= 0 for item in component.items)


def test_load_more_token_also_reads_next_page_token() -> None:
    """A shelf calls it `loadMoreToken`; a loadmore page calls it `nextPageToken`."""
    shelf = RelatedComponent.from_api({"contents": [], "loadMoreToken": "a"})
    page = RelatedComponent.from_api({"contents": [], "nextPageToken": "b"})
    assert (shelf.load_more_token, page.load_more_token) == ("a", "b")


def test_has_next_is_false_without_items() -> None:
    """An empty shelf with a token would page forever otherwise."""
    assert RelatedComponent.from_api({"contents": [], "loadMoreToken": "a"}).has_next is False


def test_request_body(related_component_payload: dict[str, Any]) -> None:
    with respx.mock as mock:
        route = mock.post(COMPONENT_URL).mock(
            return_value=httpx.Response(200, json=related_component_payload)
        )
        with Client(options=FAST) as client:
            client.related_component("m1", RelatedComponentType.SIMILAR_LOOKS, page_size=3)
    body = json.loads(route.calls[0].request.content)
    assert body["itemId"] == "m1"
    assert body["componentType"] == "COMPONENT_TYPE_SIMILAR_LOOKS"
    assert body["itemType"] == "ITEM_TYPE_MERCARI"
    assert body["pageSize"] == 3
    assert len(body["itemViewRequestId"]) == 32


def test_walk_reuses_one_view_request_id(related_component_payload: dict[str, Any]) -> None:
    with_token = {**related_component_payload, "loadMoreToken": "tok"}
    tail = {"contents": related_component_payload["contents"][:1], "nextPageToken": ""}
    with respx.mock as mock:
        component = mock.post(COMPONENT_URL).mock(return_value=httpx.Response(200, json=with_token))
        loadmore = mock.post(LOADMORE_URL).mock(return_value=httpx.Response(200, json=tail))
        with Client(options=FAST) as client:
            list(client.iter_related_items("m1"))

    first = json.loads(component.calls[0].request.content)
    second = json.loads(loadmore.calls[0].request.content)
    assert second["itemViewRequestId"] == first["itemViewRequestId"]
    assert second["pageToken"] == "tok"


def test_walk_never_sends_an_empty_token(related_component_payload: dict[str, Any]) -> None:
    """An empty `pageToken` answers 500 `invalid load more token` (probe19)."""
    payload = {**related_component_payload, "loadMoreToken": ""}
    with respx.mock as mock:
        mock.post(COMPONENT_URL).mock(return_value=httpx.Response(200, json=payload))
        loadmore = mock.post(LOADMORE_URL).mock(return_value=httpx.Response(200, json={}))
        with Client(options=FAST) as client:
            items = list(client.iter_related_items("m1"))
    assert loadmore.call_count == 0
    assert items


def test_walk_de_duplicates(related_component_payload: dict[str, Any]) -> None:
    with_token = {**related_component_payload, "loadMoreToken": "tok"}
    repeat = {"contents": related_component_payload["contents"], "nextPageToken": ""}
    unique = len({c["itemContent"]["item"]["id"] for c in related_component_payload["contents"]})
    with respx.mock as mock:
        mock.post(COMPONENT_URL).mock(return_value=httpx.Response(200, json=with_token))
        mock.post(LOADMORE_URL).mock(return_value=httpx.Response(200, json=repeat))
        with Client(options=FAST) as client:
            items = list(client.iter_related_items("m1"))
    assert len(items) == unique
