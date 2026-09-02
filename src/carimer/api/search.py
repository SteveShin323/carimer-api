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
    "SEARCH_URL",
    "build_facets_body",
    "build_search_body",
    "decode_facet_id",
    "encode_facet_id",
    "facets_request",
    "search_request",
]

SEARCH_URL = f"{BASE_URL}/v2/entities:search"
FACETS_URL = f"{BASE_URL}/v2/facets:suggest"

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
