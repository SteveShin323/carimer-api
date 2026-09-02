"""Phase 4: detail / seller / peripheral models against live-captured fixtures."""

from __future__ import annotations

from datetime import UTC
from typing import Any

import pytest

from carimer.models.enums import ItemKind, Status
from carimer.models.item import Item
from carimer.models.misc import DesiredPriceInfo, SimilarItem, Suggestion
from carimer.models.profile import EXCLUDED_FIELDS, Badge, Profile, Review, SellerItem
from carimer.models.shops import ShopsProduct
from carimer.transport.errors import ParseError

# -- personal listing detail ---------------------------------------------------


def test_item_detail_core_fields(item_detail_payload: dict[str, Any]) -> None:
    item = Item.from_api(item_detail_payload)
    assert item.id.startswith("m")
    assert item.price > 0
    assert item.status is Status.ON_SALE  # detail spells it "on_sale"
    assert item.description
    assert item.created is not None and item.created.tzinfo is UTC
    assert item.photos and item.photos[0].startswith("https://")
    assert item.seller is not None and item.seller.num_sell_items is not None
    assert item.is_shop_item is False  # "is_shop_item": "no"


def test_item_detail_accepts_data_only(item_detail_payload: dict[str, Any]) -> None:
    whole = Item.from_api(item_detail_payload)
    inner = Item.from_api(item_detail_payload["data"])
    assert whole.id == inner.id


def test_item_category_path_is_root_to_leaf(item_detail_payload: dict[str, Any]) -> None:
    item = Item.from_api(item_detail_payload)
    assert [node.id for node in item.category_path] == [7, 100, 859]
    assert item.category_id == 859


def test_filterable_attributes_differ_from_ui_attributes(item_detail_payload: dict[str, Any]) -> None:
    """色 comes with ``show_on_ui: false`` but is the filterable one (probe11)."""
    item = Item.from_api(item_detail_payload)
    ui = {attr.text for attr in item.ui_attributes}
    filterable = {attr.text for attr in item.filterable_attributes}
    assert "色" in filterable
    assert "色" not in ui
    assert "photo_description" not in filterable
    color = next(attr for attr in item.filterable_attributes if attr.text == "色")
    value_id, value_text = color.values[0]
    assert len(value_id) == 36 and value_text.endswith("系")
    assert color.id == "7bd3eacc-ae45-4d73-bc57-a611c9432014"  # the search section UUID


def test_missing_auction_info_is_none(item_detail_payload: dict[str, Any]) -> None:
    assert Item.from_api(item_detail_payload).auction is None


def test_converted_price_parses() -> None:
    item = Item.from_api(
        {
            "id": "m1",
            "name": "x",
            "price": 70000,
            "converted_price": {"price": 459.2, "currency_code": "USD", "rate_updated": 1788315002},
        }
    )
    assert item.converted_price is not None
    assert item.converted_price.currency_code == "USD"
    assert item.converted_price.price == pytest.approx(459.2)
    assert item.converted_price.rate_updated is not None


def test_detail_and_search_status_normalise_to_the_same_enum(
    item_detail_payload: dict[str, Any], search_page_payload: dict[str, Any]
) -> None:
    from carimer.models.search import SearchItem

    detail = Item.from_api(item_detail_payload)
    search = SearchItem.from_api(search_page_payload["items"][0])
    assert detail.status is search.status is Status.ON_SALE


def test_detail_auction_info_normalises_like_search_auction() -> None:
    item = Item.from_api(
        {
            "id": "m1",
            "name": "x",
            "price": 62000,
            "auction_info": {
                "id": "a1",
                "expected_end_time": 1788349140,
                "total_bids": 21,
                "highest_bid": 62100,
                "initial_price": 60000,
                "state": "STATE_ONGOING",
                "auction_type": "AUCTION_TYPE_NORMAL",
            },
        }
    )
    assert item.auction is not None
    assert item.auction.total_bids == 21
    assert item.auction.state == "STATE_ONGOING"
    assert item.auction.bid_deadline is not None


@pytest.mark.parametrize("missing", ["id", "name", "price"])
def test_item_requires_three_fields(missing: str) -> None:
    payload = {"id": "m1", "name": "x", "price": 100}
    del payload[missing]
    with pytest.raises(ParseError):
        Item.from_api(payload)


# -- shops product -------------------------------------------------------------


def test_shops_product_fields(shops_product_payload: dict[str, Any]) -> None:
    product = ShopsProduct.from_api(shops_product_payload)
    assert product.id == shops_product_payload["name"]  # payload "name" is the id
    assert product.display_name == shops_product_payload["displayName"]
    assert product.price > 0
    assert product.created is not None and product.created.tzinfo is UTC
    assert product.shop is not None and product.shop.display_name
    assert product.condition_name  # display name only; Shops has no numeric condition id
    assert product.variants and product.variants[0].id


def test_shops_sale_state_comes_from_tags(shops_product_payload: dict[str, Any]) -> None:
    """Shops products have no status field at all (01 §6)."""
    on_sale = ShopsProduct.from_api({**shops_product_payload, "productTags": []})
    sold = ShopsProduct.from_api({**shops_product_payload, "productTags": ["sold_out"]})
    assert on_sale.sold_out is False
    assert sold.sold_out is True


def test_shops_category_path_is_reversed_to_root_first(shops_product_payload: dict[str, Any]) -> None:
    product = ShopsProduct.from_api(shops_product_payload)
    raw_first = shops_product_payload["productDetail"]["categories"][0]["categoryId"]
    assert [node.id for node in product.category_path][-1] == int(raw_first)
    assert product.category_path[0].parent_id is None or product.category_path[0].id


# -- profile -------------------------------------------------------------------


def test_profile_model_has_no_personal_fields() -> None:
    fields = set(Profile.model_fields)
    assert not fields & EXCLUDED_FIELDS
    assert not any(name.startswith(("pp_", "tokushouhou_")) for name in fields)
    for name in ("email", "phone_number", "current_sales", "current_point", "iv_code", "num_ticket"):
        assert name not in fields


def test_profile_raw_is_scrubbed_too() -> None:
    """Even ``raw`` must not carry the sensitive keys the API sends."""
    profile = Profile.from_api(
        {
            "data": {
                "id": "1",
                "name": "seller",
                "created": 1601972891,
                "email": "x@example.com",
                "phone_number": "090",
                "current_sales": 1,
                "pp_show_url": "https://x",
                "tokushouhou_edit_url": "https://y",
            }
        }
    )
    assert profile.id == "1"
    assert profile.created is not None
    assert set(profile.raw) == {"id", "name", "created"}


def test_profile_parses_the_captured_response(profile_payload: dict[str, Any]) -> None:
    profile = Profile.from_api(profile_payload)
    assert profile.num_sell_items and profile.num_sell_items > 0
    assert profile.created is not None and profile.created.year > 2010
    assert profile.ratings.get("good", 0) >= 0


# -- seller items / reviews ----------------------------------------------------


def test_seller_items_parse(seller_items_payload: dict[str, Any]) -> None:
    items = [SellerItem.from_api(row) for row in seller_items_payload["data"]]
    assert items
    assert all(item.pager_id and item.pager_id > 0 for item in items)
    assert all(item.status is not Status.UNKNOWN for item in items)


def test_reviews_parse(reviews_payload: dict[str, Any]) -> None:
    reviews = [Review.from_api(row) for row in reviews_payload["data"]]
    assert reviews
    assert all(review.fame in {"good", "normal", "bad"} for review in reviews)
    assert all(review.pager_id for review in reviews)
    assert reviews_payload["meta"]["num_ratings"] >= len(reviews)


# -- peripheral ----------------------------------------------------------------


def test_similar_items_parse(similar_items_payload: dict[str, Any]) -> None:
    items = [SimilarItem.from_api(raw) for raw in similar_items_payload["items"]]
    assert items
    assert all(item.price > 0 for item in items)
    assert all(item.kind in {ItemKind.MERCARI, ItemKind.SHOPS} for item in items)


def test_suggestions_skip_unknown_wrappers(suggest_terms_payload: dict[str, Any]) -> None:
    parsed = [Suggestion.from_api(raw) for raw in suggest_terms_payload["data"]]
    suggestions = [s for s in parsed if s is not None]
    assert suggestions
    assert suggestions[0].keyword
    assert Suggestion.from_api({"SomethingElse": {}}) is None


def test_suggestion_categories(suggest_terms_payload: dict[str, Any]) -> None:
    suggestions = [s for s in (Suggestion.from_api(r) for r in suggest_terms_payload["data"]) if s]
    with_category = [s for s in suggestions if s.categories]
    assert with_category, "the capture has at least one category hint"
    category_id, name = with_category[0].categories[0]
    assert category_id > 0 and name


def test_desired_price_info(desired_price_payload: dict[str, Any]) -> None:
    info = DesiredPriceInfo.from_api(desired_price_payload)
    assert info.item_id and info.item_id.startswith("m")
    assert info.registered_count >= 0


def test_badge_parses_camel_case_icon_url() -> None:
    badge = Badge.from_api({"id": "b1", "name": "n", "description": "d", "iconUrl": "https://x"})
    assert badge.icon_url == "https://x"
