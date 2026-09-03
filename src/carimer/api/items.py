"""Item-side request builders (01 §5, §6, §8).

``get_item`` sends the same six ``include_*`` flags the web product page sends. Passing
a Shops product id here answers 400 ``InvalidArgument``, indistinguishable from a
malformed id, so the client refuses it before the request (03 §1.4).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Final

from carimer.models.enums import RelatedComponentType, ThumbnailType
from carimer.transport.base import BASE_URL, Request

__all__ = [
    "ITEM_DETAIL_FLAGS",
    "desired_price_info",
    "get_item",
    "get_shops_product",
    "related_component",
    "related_loadmore",
    "shops_products_batch",
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


def get_shops_product(product_id: str, *, image_type: ThumbnailType | None = None) -> Request:
    """The only route to a Mercari Shops product (01 §6).

    ``image_type`` is the Shops counterpart of ``thumbnailTypes``: it switches the
    suffix on the returned asset URLs (``…jpg@webp`` by default, ``…jpg@jpg`` with
    ``JPEG``). The web sends ``JPEG``.
    """
    params: dict[str, Any] = {"view": "FULL"}
    if image_type is not None:
        params["imageType"] = ThumbnailType(image_type).value
    return Request(
        "GET",
        f"{BASE_URL}/v1/marketplaces/shops/products/{product_id}",
        params=params,
    )


def shops_products_batch(product_ids: Sequence[str]) -> Request:
    """Fetch several Shops products in one call.

    ``names`` must be fully qualified — ``marketplaces/shops/products/{id}``. A bare id
    or the shorter ``products/{id}`` answers 200 with an empty list rather than an
    error (probe19), so the prefix is added here and never taken from the caller.
    """
    names = [f"marketplaces/shops/products/{pid.rsplit('/', 1)[-1]}" for pid in product_ids]
    return Request(
        "GET",
        f"{BASE_URL}/v1/marketplaces/-/products:batchGet",
        params={"names": names},
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


def related_component(
    item_id: str,
    component_type: RelatedComponentType,
    *,
    view_request_id: str,
    page_size: int = 10,
    item_type: str = "ITEM_TYPE_MERCARI",
) -> Request:
    """One recommendation shelf from the web product page (probe18).

    A different axis from ``list-similar-items``: each ``component_type`` answers its
    own titled shelf. ``view_request_id`` is the web's ``itemViewRequestId``, 32 hex
    characters shared by every call made for one item view; ``related_loadmore`` needs
    the same value.
    """
    return Request(
        "POST",
        f"{BASE_URL}/v2/relateditems/component",
        json={
            "itemId": item_id,
            "itemType": item_type,
            "itemViewRequestId": view_request_id,
            "componentType": RelatedComponentType(component_type).value,
            "pageSize": page_size,
        },
    )


def related_loadmore(*, view_request_id: str, page_token: str, page_size: int = 10) -> Request:
    """The next page of a shelf. ``page_token`` is the shelf's ``loadMoreToken``.

    An empty token answers 500 ``invalid load more token`` (probe19), so the caller must
    check that the shelf offered one.
    """
    return Request(
        "POST",
        f"{BASE_URL}/v2/relateditems/loadmore",
        json={
            "itemViewRequestId": view_request_id,
            "pageSize": page_size,
            "pageToken": page_token,
        },
    )


def desired_price_info(item_id: str) -> Request:
    return Request("GET", f"{BASE_URL}/v2/desiredPriceItems/{item_id}/desiredPriceInfo")
