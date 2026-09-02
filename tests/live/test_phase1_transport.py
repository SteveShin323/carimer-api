"""Phase 1 live checks — 3 calls (Phase 1).

The search body here is the 01 §3.1 capture written out literally: Phase 1 only owns
the transport, and ``SearchQuery`` / ``build_search_body`` arrive in Phase 2, which
re-runs this request through the builder.
"""

from __future__ import annotations

from typing import Any

import pytest

from carimer.transport import errors
from carimer.transport.base import Request
from carimer.transport.sync import SyncTransport

from .conftest import LIVE_OPTIONS

pytestmark = [pytest.mark.live, pytest.mark.phase1]

SEARCH_URL = "https://api.mercari.jp/v2/entities:search"


def _minimal_search_body(session_id: str, device_uuid: str) -> dict[str, Any]:
    return {
        "userId": "",
        "config": {"responseToggles": ["QUERY_SUGGESTION_WEB_1"]},
        "pageSize": 20,
        "pageToken": "",
        "searchSessionId": session_id,
        "source": "BaseSerp",
        "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
        "thumbnailTypes": [],
        "searchCondition": {
            "keyword": "a",
            "excludeKeyword": "",
            "sort": "SORT_SCORE",
            "order": "ORDER_DESC",
            "status": ["STATUS_ON_SALE"],
            "sizeId": [],
            "categoryId": [],
            "brandId": [],
            "sellerId": [],
            "priceMin": 0,
            "priceMax": 0,
            "itemConditionId": [],
            "shippingPayerId": [],
            "shippingFromArea": [],
            "shippingMethod": [],
            "colorId": [],
            "hasCoupon": False,
            "attributes": [],
            "itemTypes": [],
            "skuIds": [],
            "shopIds": [],
            "excludeShippingMethodIds": [],
        },
        "serviceFrom": "suruga",
        "withItemBrand": True,
        "withItemSize": False,
        "withItemPromotions": True,
        "withItemSizes": True,
        "withShopname": True,
        "useDynamicAttribute": True,
        "withSuggestedItems": True,
        "withOfferPricePromotion": True,
        "withProductSuggest": True,
        "withParentProducts": False,
        "withProductArticles": True,
        "withSearchConditionId": False,
        "withAuction": True,
        "laplaceDeviceUuid": device_uuid,
    }


def test_search_returns_200(transport: SyncTransport) -> None:
    """Call 1/3 — signed request with the five default headers."""
    body = _minimal_search_body(transport.search_session_id, transport.device_uuid)
    payload = transport.send(Request("POST", SEARCH_URL, json=body))
    assert payload["items"], "expected at least one item"
    assert int(payload["meta"]["numFound"]) > 0


def test_wrong_htu_path_is_rejected() -> None:
    """Call 2/3 — the server compares the ``htu`` path (01 §1.2)."""

    class WrongPathTransport(SyncTransport):
        def signed_url(self, request: Request) -> str:
            return "https://api.mercari.jp/v2/entities:searchXX"

    with WrongPathTransport(LIVE_OPTIONS) as bad:
        body = _minimal_search_body(bad.search_session_id, bad.device_uuid)
        with pytest.raises(errors.AuthError):
            bad.send(Request("POST", SEARCH_URL, json=body))


def test_missing_x_platform_is_rejected() -> None:
    """Call 3/3 — ``X-Platform`` is required; absence gives the same 400 as a wrong value."""

    class NoPlatformTransport(SyncTransport):
        def headers_for(self, request: Request) -> dict[str, str]:
            headers = super().headers_for(request)
            headers.pop("X-Platform", None)
            return headers

    with NoPlatformTransport(LIVE_OPTIONS) as bad:
        body = _minimal_search_body(bad.search_session_id, bad.device_uuid)
        with pytest.raises(errors.BadRequestError) as excinfo:
            bad.send(Request("POST", SEARCH_URL, json=body))
    assert excinfo.value.code == "UnsupportedVersionException"
