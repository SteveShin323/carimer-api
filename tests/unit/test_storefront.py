"""Mercari Shops storefronts — request shape, parsing and paging (01 §11)."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx

from carimer import Client, ShopProductOrder, ThumbnailType, TransportOptions
from carimer.api import shops as shops_api
from carimer.models.shops import ShopDetail, ShopReview, ShopsProductSummary
from carimer.transport.base import BASE_URL

FAST = TransportOptions(min_interval=0)
SHOP = "BR6QXaRpWFNjGzakL5KgfZ"
PRODUCTS_URL = f"{BASE_URL}/services/bff/shops/v1/shops/{SHOP}/products"
DETAILS_URL = f"{BASE_URL}/services/bff/shops/v1/contents/shops/{SHOP}/details"
REVIEWS_URL = f"{BASE_URL}/services/bff/shops/v1/contents/shops/{SHOP}/reviews"


def test_products_request_matches_the_web_call() -> None:
    request = shops_api.shop_products(SHOP)
    assert request.params == {
        "parent": f"shops/{SHOP}",
        "pageSize": 100,
        "pageToken": "",
        "filter": "",
        "orderBy": "",
        "productView": "PRODUCT_VIEW_WITH_RECOMMENDED_COUPONS",
    }


@pytest.mark.parametrize(
    ("order", "expected"),
    [
        (ShopProductOrder.NEWEST, ""),
        (ShopProductOrder.PRICE_ASC, "price asc"),
        (ShopProductOrder.PRICE_DESC, "price desc"),
    ],
)
def test_order_by_uses_the_three_values_the_web_sends(order: ShopProductOrder, expected: str) -> None:
    assert shops_api.shop_products(SHOP, order_by=order).params["orderBy"] == expected


def test_filter_is_always_empty() -> None:
    """The web never fills it and values that look right change nothing (probe15)."""
    assert shops_api.shop_products(SHOP).params["filter"] == ""
    assert shops_api.shop_reviews(SHOP).params["filter"] == ""


def test_product_summary_parsing(shop_products_payload: dict[str, Any]) -> None:
    row = shop_products_payload["products"][0]
    product = ShopsProductSummary.from_api(row)
    # `products/{id}` is normalised so the id can go straight into get_detail().
    assert "/" not in product.id
    assert row["name"].endswith(product.id)
    assert product.price == row["price"]
    assert product.thumbnails and all(uri.startswith("http") for uri in product.thumbnails)
    assert product.created is not None


def test_shop_detail_parsing(shop_details_payload: dict[str, Any]) -> None:
    detail = ShopDetail.from_api(shop_details_payload)
    assert detail.id == shop_details_payload["shopInfo"]["id"]
    assert detail.review_count == shop_details_payload["shopReviewStats"]["count"]
    assert detail.followed_count == shop_details_payload["shopFollowedCount"]
    assert detail.policies  # businessDays / sellingPrice / …
    assert detail.created is not None  # unix seconds as a string


def test_shop_review_parsing(shop_reviews_payload: dict[str, Any]) -> None:
    review = ShopReview.from_api(shop_reviews_payload["productReviews"][0])
    assert review.id
    assert review.rating and review.rating.startswith("RATING_")
    assert review.is_good is (review.rating == "RATING_GOOD")
    assert review.product_name


def test_iter_products_follows_the_page_token(shop_products_payload: dict[str, Any]) -> None:
    first = {**shop_products_payload, "nextPageToken": "tok"}
    last = {**shop_products_payload, "nextPageToken": ""}
    with respx.mock as mock:
        route = mock.get(PRODUCTS_URL).mock(
            side_effect=[httpx.Response(200, json=first), httpx.Response(200, json=last)]
        )
        with Client(options=FAST) as client:
            products = list(client.shops.iter_products(SHOP))
    assert route.call_count == 2
    assert route.calls[1].request.url.params["pageToken"] == "tok"
    assert len(products) == 2 * len(shop_products_payload["products"])


def test_iter_products_honours_max_items(shop_products_payload: dict[str, Any]) -> None:
    payload = {**shop_products_payload, "nextPageToken": "tok"}
    with respx.mock as mock:
        mock.get(PRODUCTS_URL).mock(return_value=httpx.Response(200, json=payload))
        with Client(options=FAST) as client:
            products = list(client.shops.iter_products(SHOP, max_items=2))
    assert len(products) == 2


def test_iter_reviews_stops_on_an_empty_page(shop_reviews_payload: dict[str, Any]) -> None:
    empty: dict[str, Any] = {"productReviews": [], "nextPageToken": "tok"}
    with respx.mock as mock:
        route = mock.get(REVIEWS_URL).mock(
            side_effect=[
                httpx.Response(200, json={**shop_reviews_payload, "nextPageToken": "tok"}),
                httpx.Response(200, json=empty),
            ]
        )
        with Client(options=FAST) as client:
            reviews = list(client.shops.iter_reviews(SHOP))
    assert route.call_count == 2
    assert len(reviews) == len(shop_reviews_payload["productReviews"])


def test_details(shop_details_payload: dict[str, Any]) -> None:
    with respx.mock as mock:
        mock.get(DETAILS_URL).mock(return_value=httpx.Response(200, json=shop_details_payload))
        with Client(options=FAST) as client:
            detail = client.shops.details(SHOP)
    assert detail.name


def test_batch_products_qualifies_every_name(shops_product_payload: dict[str, Any]) -> None:
    """A bare id or `products/{id}` answers 200 with an empty list (probe19)."""
    url = f"{BASE_URL}/v1/marketplaces/-/products:batchGet"
    with respx.mock as mock:
        route = mock.get(url).mock(
            return_value=httpx.Response(200, json={"products": [shops_product_payload]})
        )
        with Client(options=FAST) as client:
            products = client.shops.batch_products(["abc", "products/def"])
    names = route.calls[0].request.url.params.get_list("names")
    assert names == [
        "marketplaces/shops/products/abc",
        "marketplaces/shops/products/def",
    ]
    assert len(products) == 1


def test_batch_products_sends_nothing_for_an_empty_list() -> None:
    with respx.mock, Client(options=FAST) as client:
        assert client.shops.batch_products([]) == []


def test_shops_product_detail_image_type() -> None:
    assert "imageType" not in shops_api.shop_details(SHOP).params
    from carimer.api import items as items_api

    assert items_api.get_shops_product("x").params == {"view": "FULL"}
    assert items_api.get_shops_product("x", image_type=ThumbnailType.JPEG).params == {
        "view": "FULL",
        "imageType": "JPEG",
    }
