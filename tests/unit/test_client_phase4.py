"""Phase 4: client routing, paging and master-data rules (respx-mocked)."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from carimer import AsyncClient, Client, ShopsItemError, TransportOptions
from carimer.api import master as master_api
from carimer.models.item import Item
from carimer.models.search import SearchItem
from carimer.models.shops import ShopsProduct
from carimer.transport.base import BASE_URL
from carimer.transport.errors import NotFoundError

FAST = TransportOptions(min_interval=0)
ITEM_URL = f"{BASE_URL}/items/get"
GET_ITEMS_URL = f"{BASE_URL}/items/get_items"
REVIEWS_URL = f"{BASE_URL}/reviews/history"
SHOPS_ID = "2JVoP4vefPkskNLnvGbb9P"


def _item_response(item_id: str = "m1") -> httpx.Response:
    return httpx.Response(
        200, json={"result": "OK", "data": {"id": item_id, "name": "x", "price": 1000, "status": "on_sale"}}
    )


# -- routing -------------------------------------------------------------------


def test_get_item_rejects_a_shops_id_without_any_request() -> None:
    """The server's 400 here is indistinguishable from a malformed id (01 §5)."""
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(ITEM_URL)
        with Client(options=FAST) as client, pytest.raises(ShopsItemError):
            client.get_item(SHOPS_ID)
    assert route.call_count == 0


def test_get_item_sends_the_six_web_include_flags() -> None:
    with respx.mock as mock:
        route = mock.get(ITEM_URL).mock(return_value=_item_response())
        with Client(options=FAST) as client:
            item = client.get_item("m1")
    params = route.calls[0].request.url.params
    assert params["id"] == "m1"
    for flag in (
        "include_item_attributes",
        "include_product_page_component",
        "include_non_ui_item_attributes",
        "include_donation",
        "include_item_attributes_sections",
        "include_auction",
    ):
        assert params[flag] == "true"
    assert "country_code" not in params
    assert isinstance(item, Item)


def test_country_code_is_forwarded() -> None:
    with respx.mock as mock:
        route = mock.get(ITEM_URL).mock(return_value=_item_response())
        with Client(options=FAST) as client:
            client.get_item("m1", country_code="US")
    assert route.calls[0].request.url.params["country_code"] == "US"


def test_get_detail_routes_on_kind_then_on_id_shape(shops_product_payload: dict[str, Any]) -> None:
    shops_url = f"{BASE_URL}/v1/marketplaces/shops/products/{shops_product_payload['name']}"
    with respx.mock as mock:
        item_route = mock.get(ITEM_URL).mock(return_value=_item_response("m77574104522"))
        shops_route = mock.get(shops_url).mock(return_value=httpx.Response(200, json=shops_product_payload))
        with Client(options=FAST) as client:
            personal = client.get_detail("m77574104522")
            by_id = client.get_detail(shops_product_payload["name"])
            by_kind = client.get_detail(
                SearchItem.from_api(
                    {
                        "id": shops_product_payload["name"],
                        "name": "x",
                        "price": "1",
                        "itemType": "ITEM_TYPE_BEYOND",
                    }
                )
            )
    assert isinstance(personal, Item)
    assert isinstance(by_id, ShopsProduct)
    assert isinstance(by_kind, ShopsProduct)
    assert item_route.call_count == 1
    assert shops_route.call_count == 2
    assert shops_route.calls[0].request.url.params["view"] == "FULL"


def test_missing_item_maps_to_not_found() -> None:
    body = {"result": "error", "errors": [{"code": "RecordNotFoundException", "message": "no item"}]}
    with respx.mock as mock:
        mock.get(ITEM_URL).mock(return_value=httpx.Response(404, json=body))
        with Client(options=FAST) as client, pytest.raises(NotFoundError):
            client.get_item("m00000000000")


# -- profile -------------------------------------------------------------------


def test_profile_always_sends_user_format() -> None:
    """Without it ``created``/``num_sell_items`` come back 0 (mercapi-node 0.2.0 bug)."""
    url = f"{BASE_URL}/users/get_profile"
    with respx.mock as mock:
        route = mock.get(url).mock(
            return_value=httpx.Response(200, json={"result": "OK", "data": {"id": "1", "created": 1}})
        )
        with Client(options=FAST) as client:
            client.get_profile("1")
    assert route.calls[0].request.url.params["_user_format"] == "profile"


# -- max_pager_id paging -------------------------------------------------------


def _rows(ids: list[str], start_pager: int) -> list[dict[str, Any]]:
    return [
        {"id": item_id, "name": item_id, "price": 100, "status": "on_sale", "pager_id": start_pager - i}
        for i, item_id in enumerate(ids)
    ]


def test_seller_items_paging_uses_min_pager_id_minus_one() -> None:
    pages = [
        httpx.Response(200, json={"data": _rows(["m1", "m2"], 500), "meta": {"has_next": True}}),
        httpx.Response(200, json={"data": _rows(["m3"], 498), "meta": {"has_next": False}}),
    ]
    with respx.mock as mock:
        route = mock.get(GET_ITEMS_URL).mock(side_effect=pages)
        with Client(options=FAST) as client:
            items = list(client.iter_seller_items("1", limit=2))
    assert [item.id for item in items] == ["m1", "m2", "m3"]
    first, second = route.calls[0].request.url.params, route.calls[1].request.url.params
    assert "max_pager_id" not in first
    assert first["status"] == "on_sale"
    assert first["with_auction"] == "true"
    assert second["max_pager_id"] == "498"  # min(500, 499) - 1


def test_seller_items_stops_when_has_next_is_false() -> None:
    with respx.mock as mock:
        route = mock.get(GET_ITEMS_URL).mock(
            return_value=httpx.Response(200, json={"data": _rows(["m1"], 5), "meta": {"has_next": False}})
        )
        with Client(options=FAST) as client:
            assert len(list(client.iter_seller_items("1"))) == 1
    assert route.call_count == 1


def test_seller_items_deduplicates_and_honours_max_items() -> None:
    pages = [
        httpx.Response(200, json={"data": _rows(["m1", "m2"], 9), "meta": {"has_next": True}}),
        httpx.Response(200, json={"data": _rows(["m2", "m3"], 7), "meta": {"has_next": True}}),
    ]
    with respx.mock as mock:
        mock.get(GET_ITEMS_URL).mock(side_effect=pages)
        with Client(options=FAST) as client:
            assert [i.id for i in client.iter_seller_items("1", max_pages=2)] == ["m1", "m2", "m3"]

    with respx.mock as mock:
        mock.get(GET_ITEMS_URL).mock(
            return_value=httpx.Response(
                200, json={"data": _rows(["m1", "m2"], 9), "meta": {"has_next": True}}
            )
        )
        with Client(options=FAST) as client:
            assert [i.id for i in client.iter_seller_items("1", max_items=1)] == ["m1"]


def test_reviews_paging() -> None:
    def review_rows(pager_start: int) -> list[dict[str, Any]]:
        return [
            {"subject": "seller", "fame": "good", "message": "m", "pager_id": pager_start - i}
            for i in range(2)
        ]

    pages = [
        httpx.Response(200, json={"data": review_rows(100), "meta": {"has_next": True}}),
        httpx.Response(200, json={"data": review_rows(98), "meta": {"has_next": False}}),
    ]
    with respx.mock as mock:
        route = mock.get(REVIEWS_URL).mock(side_effect=pages)
        with Client(options=FAST) as client:
            reviews = list(client.iter_reviews("1", limit=2))
    assert len(reviews) == 4
    assert route.calls[1].request.url.params["max_pager_id"] == "98"
    assert route.calls[0].request.url.params["subject"] == "seller,buyer"
    assert route.calls[0].request.url.params["fame"] == "good,normal,bad"


def test_limit_over_100_is_rejected_client_side() -> None:
    """200 answers 400 ``InvalidRequest`` (01 §7.2), so refuse before sending."""
    from carimer.api import users as users_api

    with pytest.raises(ValueError, match="100"):
        users_api.get_seller_items("1", limit=200)
    with pytest.raises(ValueError, match="100"):
        users_api.get_reviews("1", limit=200)


# -- master data ---------------------------------------------------------------


def test_master_v2_uses_the_exact_accept_header_and_path() -> None:
    url = f"{BASE_URL}/master/v2/datasets/item_categories"
    with respx.mock as mock:
        route = mock.get(url).mock(return_value=httpx.Response(200, json={"itemCategories": []}))
        with Client(options=FAST) as client:
            client.master("item_categories")
    assert route.calls[0].request.headers["accept"] == "application/json"


def test_master_v1_path_and_default_accept() -> None:
    url = f"{BASE_URL}/services/master/v1/itemConditions"
    with respx.mock as mock:
        route = mock.get(url).mock(return_value=httpx.Response(200, json={"conditions": []}))
        with Client(options=FAST) as client:
            client.master("itemConditions")
    assert route.calls[0].request.headers["accept"] == "application/json, text/plain, */*"


def test_shipping_from_areas_is_a_known_v1_dataset() -> None:
    """The names behind `SearchQuery.shipping_from()`, which has no web UI."""
    request = master_api.dataset("shippingFromAreas")
    assert request.url.endswith("/services/master/v1/shippingFromAreas")


def test_unknown_master_name_raises_value_error() -> None:
    with pytest.raises(ValueError, match="unknown master dataset"):
        master_api.dataset("foo")
    with Client(options=FAST) as client, pytest.raises(ValueError):
        client.master("foo")


# -- peripheral ----------------------------------------------------------------


def test_similar_items_body(similar_items_payload: dict[str, Any]) -> None:
    url = f"{BASE_URL}/v2/relateditems/list-similar-items"
    with respx.mock as mock:
        route = mock.post(url).mock(return_value=httpx.Response(200, json=similar_items_payload))
        with Client(options=FAST) as client:
            items = client.similar_items("m1", limit=5)
    body = json.loads(route.calls[0].request.content)
    assert body == {
        "itemId": "m1",
        "pageSize": 5,
        "itemTypesFlag": "ITEM_TYPES_MERCARI_AND_SHOPS",
        "includeAds": False,
        "pageToken": "",
    }
    assert items


def test_badges_and_identity_verification() -> None:
    badges_url = f"{BASE_URL}/services/usersocialjp/v1/stats/badges"
    verified_url = f"{BASE_URL}/services/usersocialjp/v1/stats/has_identity_verified_badge"
    with respx.mock as mock:
        badge_route = mock.post(badges_url).mock(
            return_value=httpx.Response(200, json={"badges": [{"id": "b", "name": "n"}]})
        )
        mock.post(verified_url).mock(return_value=httpx.Response(200, json={"hasBadge": True}))
        with Client(options=FAST) as client:
            badges = client.seller_badges("1")
            verified = client.is_identity_verified("1")
    assert [badge.id for badge in badges] == ["b"]
    assert verified is True
    # The flag, not the field name, is what unlocks badge 10100 (probe13d).
    assert json.loads(badge_route.calls[0].request.content) == {
        "user_id": "1",
        "fetch_seller_rank_badge": True,
    }


def test_suggest_keywords(suggest_terms_payload: dict[str, Any]) -> None:
    url = f"{BASE_URL}/search_index/terms"
    with respx.mock as mock:
        route = mock.get(url).mock(return_value=httpx.Response(200, json=suggest_terms_payload))
        with Client(options=FAST) as client:
            suggestions = client.suggest_keywords("iphone")
    assert suggestions
    assert route.calls[0].request.url.params["brand_category_result_included"] == "true"
    assert "category_id" not in route.calls[0].request.url.params


def test_suggest_keywords_can_be_scoped_to_a_category(
    suggest_terms_payload: dict[str, Any],
) -> None:
    """The web search box sends it and it changes the result set outright (probe15)."""
    url = f"{BASE_URL}/search_index/terms"
    with respx.mock as mock:
        route = mock.get(url).mock(return_value=httpx.Response(200, json=suggest_terms_payload))
        with Client(options=FAST) as client:
            client.suggest_keywords("リング", category_id=83)
    assert route.calls[0].request.url.params["category_id"] == "83"


def test_seller_items_can_exclude_archived() -> None:
    url = f"{BASE_URL}/items/get_items"
    body = {"data": [], "meta": {"has_next": False}}
    with respx.mock as mock:
        route = mock.get(url).mock(return_value=httpx.Response(200, json=body))
        with Client(options=FAST) as client:
            list(client.iter_seller_items("1"))
            list(client.iter_seller_items("1", exclude_archived=True))
    assert "exclude_archived_item" not in route.calls[0].request.url.params
    assert route.calls[1].request.url.params["exclude_archived_item"] == "true"


# -- async parity --------------------------------------------------------------


async def test_async_client_detail_and_paging(shops_product_payload: dict[str, Any]) -> None:
    shops_url = f"{BASE_URL}/v1/marketplaces/shops/products/{shops_product_payload['name']}"
    with respx.mock as mock:
        mock.get(ITEM_URL).mock(return_value=_item_response())
        mock.get(shops_url).mock(return_value=httpx.Response(200, json=shops_product_payload))
        mock.get(GET_ITEMS_URL).mock(
            return_value=httpx.Response(200, json={"data": _rows(["m1"], 3), "meta": {"has_next": False}})
        )
        async with AsyncClient(options=FAST) as client:
            assert isinstance(await client.get_item("m1"), Item)
            assert isinstance(await client.get_detail(shops_product_payload["name"]), ShopsProduct)
            assert [item.id async for item in client.iter_seller_items("1")] == ["m1"]
            with pytest.raises(ShopsItemError):
                await client.get_item(SHOPS_ID)
