"""Item-side request builders (01 §5, §6, §8).

``get_item`` sends the same six ``include_*`` flags the web product page sends. Passing
a Shops product id here answers 400 ``InvalidArgument``, indistinguishable from a
malformed id, so the client refuses it before the request (03 §1.4).
"""

from __future__ import annotations

from typing import Any, Final

from carimer.transport.base import BASE_URL, Request

__all__ = [
    "ITEM_DETAIL_FLAGS",
    "desired_price_info",
    "get_item",
    "get_shops_product",
    "similar_items",
]

#: The web product page's include flags (01 §5).
ITEM_DETAIL_FLAGS: Final = {
    "include_item_attributes": "true",
    "include_product_page_component": "true",
    "include_non_ui_item_attributes": "true",
    "include_donation": "true",
    "include_item_attributes_sections": "true",
    "include_auction": "true",
}


def get_item(item_id: str, *, country_code: str | None = None) -> Request:
    """``country_code`` adds ``converted_price`` in that currency."""
    params: dict[str, Any] = {"id": item_id, **ITEM_DETAIL_FLAGS}
    if country_code:
        params["country_code"] = country_code
    return Request("GET", f"{BASE_URL}/items/get", params=params)


def get_shops_product(product_id: str) -> Request:
    """The only route to a Mercari Shops product (01 §6)."""
    return Request(
        "GET",
        f"{BASE_URL}/v1/marketplaces/shops/products/{product_id}",
        params={"view": "FULL"},
    )


def similar_items(item_id: str, *, limit: int = 15, page_token: str = "") -> Request:
    return Request(
        "POST",
        f"{BASE_URL}/v2/relateditems/list-similar-items",
        json={
            "itemId": item_id,
            "pageSize": limit,
            "itemTypesFlag": "ITEM_TYPES_MERCARI_AND_SHOPS",
            "includeAds": False,
            "pageToken": page_token,
        },
    )


def desired_price_info(item_id: str) -> Request:
    return Request("GET", f"{BASE_URL}/v2/desiredPriceItems/{item_id}/desiredPriceInfo")
