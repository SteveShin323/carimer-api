"""Mercari Shops storefront request builders (`services/bff/shops/v1/*`).

A backend-for-frontend, so the shapes differ from the rest of the API: resource names
are `shops/{id}` / `products/{id}` paths, listings page with `pageToken`, and every
listing takes the same four query parameters.

Scope is deliberately the readable storefront — products, the shop itself and its
reviews. The Shops home, the category shelves, coupons and the merchandising sections
are curation UI and are left out even though their builders would be trivial.

`filter` is sent empty because that is what the web sends and because values that look
like the obvious syntax (`price > 1000`) change nothing and raise nothing (probe15).
"""

from __future__ import annotations

from typing import Any

from carimer.models.enums import ShopProductOrder
from carimer.transport.base import BASE_URL, Request

__all__ = [
    "MAX_PRODUCTS_PAGE_SIZE",
    "MAX_REVIEWS_PAGE_SIZE",
    "shop_details",
    "shop_products",
    "shop_reviews",
]

_BFF = f"{BASE_URL}/services/bff/shops/v1"

#: What the web sends. Larger values are untested.
MAX_PRODUCTS_PAGE_SIZE = 100
MAX_REVIEWS_PAGE_SIZE = 20


def shop_products(
    shop_id: str,
    *,
    page_size: int = MAX_PRODUCTS_PAGE_SIZE,
    page_token: str = "",
    order_by: ShopProductOrder = ShopProductOrder.NEWEST,
) -> Request:
    """A storefront's products.

    `order_by` is the web's three sort buttons. An unknown value is ignored silently
    rather than rejected, which is why it is an enum here.
    """
    params: dict[str, Any] = {
        "parent": f"shops/{shop_id}",
        "pageSize": page_size,
        "pageToken": page_token,
        "filter": "",
        "orderBy": ShopProductOrder(order_by).value,
        "productView": "PRODUCT_VIEW_WITH_RECOMMENDED_COUPONS",
    }
    return Request("GET", f"{_BFF}/shops/{shop_id}/products", params=params)


def shop_details(shop_id: str) -> Request:
    """The storefront itself: `shopInfo` plus `shopReviewStats`."""
    return Request(
        "GET",
        f"{_BFF}/contents/shops/{shop_id}/details",
        params={"name": f"shops/{shop_id}", "view": "SHOP_DETAIL_VIEW_WITH_STATS"},
    )


def shop_reviews(
    shop_id: str,
    *,
    page_size: int = MAX_REVIEWS_PAGE_SIZE,
    page_token: str = "",
) -> Request:
    """Buyer reviews left on that storefront's products."""
    params: dict[str, Any] = {
        "parent": f"shops/{shop_id}",
        "pageSize": page_size,
        "pageToken": page_token,
        "filter": "",
        "orderBy": "",
        "view": "PRODUCT_REVIEW_VIEW_DETAILED",
    }
    return Request("GET", f"{_BFF}/contents/shops/{shop_id}/reviews", params=params)
