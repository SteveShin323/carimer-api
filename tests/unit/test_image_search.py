"""Image search — body shape, page parsing and the upload-once walk (01 §10)."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import pytest
import respx

from carimer import Client, ImageSearchPage, SearchQuery, TransportOptions
from carimer.api.search import IMAGE_SEARCH_URL, build_image_search_body
from carimer.search.image import encode_image

FAST = TransportOptions(min_interval=0)
PIXEL = b"\xff\xd8\xff\xe0jpeg-bytes"

# Top-level keys of the call the web makes (probe20).
CAPTURE_TOP_LEVEL_KEYS = {
    "userId",
    "searchSessionId",
    "pageSize",
    "config",
    "imageSearchCondition",
    "pageToken",
}


def _body(**kwargs: Any) -> dict[str, Any]:
    kwargs.setdefault("photo_b64", "Zm9v")
    return build_image_search_body(SearchQuery("x").to_condition(), session_id="0" * 32, **kwargs)


def test_body_key_set_matches_the_capture() -> None:
    assert set(_body()) == CAPTURE_TOP_LEVEL_KEYS


def test_body_forces_similarity_sort_whatever_the_query_says() -> None:
    condition = SearchQuery("x").to_condition()
    assert condition["sort"] == "SORT_SCORE"
    body = build_image_search_body(condition, photo_b64="Zm9v", session_id="0" * 32)
    assert body["imageSearchCondition"]["searchCondition"]["sort"] == "SORT_SIMILARITY"
    # The caller's condition is not mutated.
    assert condition["sort"] == "SORT_SCORE"


def test_body_carries_the_rest_of_the_filters() -> None:
    condition = SearchQuery("x").price(1000, 5000).to_condition()
    body = build_image_search_body(condition, photo_b64="Zm9v", session_id="0" * 32)
    inner = body["imageSearchCondition"]["searchCondition"]
    assert (inner["priceMin"], inner["priceMax"]) == (1000, 5000)


def test_first_page_sends_the_binary_and_later_pages_send_the_id() -> None:
    first = _body()["imageSearchCondition"]
    assert first["photoBinary"] == "Zm9v"
    assert "imageId" not in first
    later = _body(photo_b64=None, image_id="img-1")["imageSearchCondition"]
    assert later["imageId"] == "img-1"
    assert "photoBinary" not in later


@pytest.mark.parametrize(
    "kwargs",
    [{"photo_b64": None, "image_id": None}, {"photo_b64": "Zm9v", "image_id": "img-1"}],
)
def test_exactly_one_image_source_is_required(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        build_image_search_body(SearchQuery("x").to_condition(), session_id="0" * 32, **kwargs)


def test_encode_image_accepts_bytes_and_paths(tmp_path: Any) -> None:
    assert encode_image(PIXEL) == base64.b64encode(PIXEL).decode()
    path = tmp_path / "probe.jpg"
    path.write_bytes(PIXEL)
    assert encode_image(path) == encode_image(PIXEL)
    assert encode_image(str(path)) == encode_image(PIXEL)


def test_encode_image_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        encode_image(b"")


def test_page_parses_the_top_level_token_and_image(image_search_payload: dict[str, Any]) -> None:
    page = ImageSearchPage.from_api(image_search_payload)
    assert page.items
    # Unlike entities:search, the token is top level and there is no numFound at all.
    assert page.next_page_token == image_search_payload["nextPageToken"]
    assert page.image_id == image_search_payload["image"]["id"]
    assert page.search_condition_echo["sort"] == "SORT_SIMILARITY"


def test_page_collects_category_suggestions(image_search_payload: dict[str, Any]) -> None:
    page = ImageSearchPage.from_api(image_search_payload)
    assert page.category_suggestions
    assert all(s.category_id and s.title for s in page.category_suggestions)


def test_walk_uploads_once_then_quotes_the_image_id(
    image_search_payload: dict[str, Any],
) -> None:
    second = {**image_search_payload, "nextPageToken": ""}
    with respx.mock as mock:
        route = mock.post(IMAGE_SEARCH_URL).mock(
            side_effect=[
                httpx.Response(200, json=image_search_payload),
                httpx.Response(200, json=second),
            ]
        )
        with Client(options=FAST) as client:
            pages = list(client.iter_image_pages(PIXEL, max_pages=5))

    assert len(pages) == 2
    first_body = json.loads(route.calls[0].request.content)["imageSearchCondition"]
    later_body = json.loads(route.calls[1].request.content)["imageSearchCondition"]
    assert first_body["photoBinary"] == base64.b64encode(PIXEL).decode()
    assert "photoBinary" not in later_body
    assert later_body["imageId"] == image_search_payload["image"]["id"]
    assert json.loads(route.calls[1].request.content)["pageToken"] == (image_search_payload["nextPageToken"])


def test_walk_flags_truncation_at_the_cap(image_search_payload: dict[str, Any]) -> None:
    """There is no approx_total here, so the flag is the only signal of what was left."""
    with respx.mock as mock:
        mock.post(IMAGE_SEARCH_URL).mock(return_value=httpx.Response(200, json=image_search_payload))
        with Client(options=FAST) as client:
            pages = list(client.iter_image_pages(PIXEL, max_pages=2))
    assert [page.truncated for page in pages] == [False, True]


def test_walk_does_not_flag_truncation_when_the_results_ran_out(
    image_search_payload: dict[str, Any],
) -> None:
    payload = {**image_search_payload, "nextPageToken": ""}
    with respx.mock as mock:
        mock.post(IMAGE_SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))
        with Client(options=FAST) as client:
            pages = list(client.iter_image_pages(PIXEL, max_pages=1))
    assert pages[0].truncated is False


def test_walk_stops_when_the_page_has_no_token(image_search_payload: dict[str, Any]) -> None:
    payload = {**image_search_payload, "nextPageToken": ""}
    with respx.mock as mock:
        route = mock.post(IMAGE_SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))
        with Client(options=FAST) as client:
            pages = list(client.iter_image_pages(PIXEL, max_pages=5))
    assert len(pages) == 1
    assert route.call_count == 1


def test_iter_items_de_duplicates_across_pages(image_search_payload: dict[str, Any]) -> None:
    last = {**image_search_payload, "nextPageToken": ""}
    unique = len({item["id"] for item in image_search_payload["items"]})
    with respx.mock as mock:
        mock.post(IMAGE_SEARCH_URL).mock(
            side_effect=[
                httpx.Response(200, json=image_search_payload),
                httpx.Response(200, json=last),
            ]
        )
        with Client(options=FAST) as client:
            items = list(client.iter_image_items(PIXEL, max_pages=5))
    assert len(items) == unique
