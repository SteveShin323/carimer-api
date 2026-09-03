"""Request builders for ``entities:search`` and ``facets:suggest`` (01 §3.1, §4.1).

Pure functions: they take a serialised ``searchCondition`` and return a
:class:`~carimer.transport.base.Request`. The bodies reproduce the web-app capture key
for key, including fields the server appears to ignore (03 §1.1) — a body that differs
takes a different index and returns different results (01 §3.1).
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from typing import Any

from carimer.transport.base import BASE_URL, Request

__all__ = [
    "FACETS_URL",
    "IMAGE_SEARCH_URL",
    "SEARCH_URL",
    "build_facets_body",
    "build_image_search_body",
    "build_search_body",
    "decode_facet_id",
    "encode_facet_id",
    "facets_request",
    "image_search_request",
    "search_request",
]

SEARCH_URL = f"{BASE_URL}/v2/entities:search"
FACETS_URL = f"{BASE_URL}/v2/facets:suggest"
IMAGE_SEARCH_URL = f"{BASE_URL}/v2/entities:imageSearch"

#: ASCII unit separator, used inside ``facetId``.
_US = "\x1f"


def build_search_body(
    condition: dict[str, Any],
    *,
    page_token: str = "",
    page_size: int = 120,
    session_id: str,
    device_uuid: str,
    with_shopname: bool = True,
    with_search_condition_id: bool = False,
    thumbnail_types: Sequence[str] = (),
) -> dict[str, Any]:
    """The web app's search body.

    ``with_shopname`` defaults to ``True`` (the web sends ``false``): it costs nothing
    and fills ``shopName`` for Shops results (01 §3.1).

    ``thumbnail_types`` accepts ``WEBP`` / ``JPEG``; anything else answers 400. Empty
    (the default, and what the web sends) yields webp URLs.
    """
    return {
        "userId": "",
        "config": {"responseToggles": ["QUERY_SUGGESTION_WEB_1"]},
        "pageSize": page_size,
        "pageToken": page_token,
        "searchSessionId": session_id,
        "source": "BaseSerp",
        "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
        "thumbnailTypes": list(thumbnail_types),
        "searchCondition": condition,
        "serviceFrom": "suruga",
        "withItemBrand": True,
        "withItemSize": False,
        "withItemPromotions": True,
        "withItemSizes": True,
        "withShopname": with_shopname,
        "useDynamicAttribute": True,
        "withSuggestedItems": True,
        "withOfferPricePromotion": True,
        "withProductSuggest": True,
        "withParentProducts": False,
        "withProductArticles": True,
        "withSearchConditionId": with_search_condition_id,
        "withAuction": True,
        "laplaceDeviceUuid": device_uuid,
    }


def search_request(
    condition: dict[str, Any],
    *,
    page_token: str = "",
    page_size: int = 120,
    session_id: str,
    device_uuid: str,
    with_shopname: bool = True,
    with_search_condition_id: bool = False,
    thumbnail_types: Sequence[str] = (),
) -> Request:
    body = build_search_body(
        condition,
        page_token=page_token,
        page_size=page_size,
        session_id=session_id,
        device_uuid=device_uuid,
        with_shopname=with_shopname,
        with_search_condition_id=with_search_condition_id,
        thumbnail_types=thumbnail_types,
    )
    return Request("POST", SEARCH_URL, json=body)


def build_image_search_body(
    condition: dict[str, Any],
    *,
    photo_b64: str | None = None,
    image_id: str | None = None,
    page_token: str = "",
    page_size: int = 30,
    session_id: str,
) -> dict[str, Any]:
    """The image-search body (probe18, probe20).

    Exactly one of ``photo_b64`` (base64 of the image bytes) and ``image_id`` is sent:
    the first request uploads the picture, and every later page refers to it by the
    ``image.id`` the first response returned. Sending the binary again on page two also
    works but re-uploads for nothing.

    ``condition`` is a normal ``searchCondition`` — every filter applies — except that
    ``sort`` is forced to ``SORT_SIMILARITY``, which is what the endpoint echoes back.

    The maximum accepted image size is unknown; a 32×32 JPEG is the only size verified.
    """
    if (photo_b64 is None) == (image_id is None):
        raise ValueError("pass exactly one of photo_b64 and image_id")
    image_condition: dict[str, Any] = {"searchCondition": {**condition, "sort": "SORT_SIMILARITY"}}
    if photo_b64 is not None:
        image_condition["photoBinary"] = photo_b64
    else:
        image_condition["imageId"] = image_id
    return {
        "userId": "",
        "searchSessionId": session_id,
        "pageSize": page_size,
        "config": {"responseToggles": ["WITH_FILTERING", "WITH_CATEGORY_FACETS_SUGGEST"]},
        "imageSearchCondition": image_condition,
        "pageToken": page_token,
    }


def image_search_request(
    condition: dict[str, Any],
    *,
    photo_b64: str | None = None,
    image_id: str | None = None,
    page_token: str = "",
    page_size: int = 30,
    session_id: str,
) -> Request:
    body = build_image_search_body(
        condition,
        photo_b64=photo_b64,
        image_id=image_id,
        page_token=page_token,
        page_size=page_size,
        session_id=session_id,
    )
    return Request("POST", IMAGE_SEARCH_URL, json=body)


def build_facets_body(
    condition: dict[str, Any],
    facet_id: str,
    *,
    facet_query: str | None = None,
    with_selected: bool = False,
    with_relevant: bool = True,
    session_id: str,
) -> dict[str, Any]:
    """``facets:suggest`` body. ``facet_query`` is omitted entirely when ``None``."""
    request: dict[str, Any] = {
        "facetId": facet_id,
        "withSelectedPaths": with_selected,
        "withRelevantFacets": with_relevant,
        "config": {"responseToggles": ["DFF_IMPROVEMENT_FACETS_REORDER"]},
    }
    if facet_query is not None:
        request["facetQuery"] = facet_query
    return {
        "facetRequests": [request],
        "searchSessionId": session_id,
        "searchCondition": condition,
        "useNtiersCategory": True,
        "useDynamicAttribute": True,
    }


def facets_request(
    condition: dict[str, Any],
    facet_id: str,
    *,
    facet_query: str | None = None,
    with_selected: bool = False,
    with_relevant: bool = True,
    session_id: str,
) -> Request:
    body = build_facets_body(
        condition,
        facet_id,
        facet_query=facet_query,
        with_selected=with_selected,
        with_relevant=with_relevant,
        session_id=session_id,
    )
    return Request("POST", FACETS_URL, json=body)


def encode_facet_id(key: str, value: str = "") -> str:
    """``"1\\x1f" + base64(key + "\\x1f" + value)``.

    Standard base64 with ``+/`` and ``=`` padding — *not* the base64url used for DPoP
    (01 §4.1). An empty ``value`` asks for the top level of that key.
    """
    payload = f"{key}{_US}{value}".encode()
    return f"1{_US}{base64.b64encode(payload).decode('ascii')}"


def decode_facet_id(facet_id: str) -> tuple[str, str]:
    """Inverse of :func:`encode_facet_id`; returns ``(key, value)``."""
    _, _, encoded = facet_id.partition(_US)
    decoded = base64.b64decode(encoded).decode("utf-8")
    key, _, value = decoded.partition(_US)
    return key, value
