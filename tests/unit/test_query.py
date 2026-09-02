"""Phase 2: ``SearchQuery`` serialisation, type rules and validation (01 §3.1-3.2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from carimer.models.enums import Condition, ItemType, Order, ShippingMethod, ShippingPayer, Sort, Status
from carimer.search.attributes import AttributeFilter
from carimer.search.query import JST_OFFSET_SECONDS, SearchQuery, as_query

# The 22 keys of the web-app capture, 01 §3.1.
CAPTURE_CONDITION_KEYS = {
    "keyword",
    "excludeKeyword",
    "sort",
    "order",
    "status",
    "sizeId",
    "categoryId",
    "brandId",
    "sellerId",
    "priceMin",
    "priceMax",
    "itemConditionId",
    "shippingPayerId",
    "shippingFromArea",
    "shippingMethod",
    "colorId",
    "hasCoupon",
    "attributes",
    "itemTypes",
    "skuIds",
    "shopIds",
    "excludeShippingMethodIds",
}


def test_default_condition_has_exactly_the_capture_keys() -> None:
    assert set(SearchQuery("x").to_condition()) == CAPTURE_CONDITION_KEYS
    assert len(CAPTURE_CONDITION_KEYS) == 22


def test_web_defaults() -> None:
    condition = SearchQuery("x").to_condition()
    assert condition["status"] == ["STATUS_ON_SALE"]
    assert condition["sort"] == "SORT_SCORE"
    assert condition["order"] == "ORDER_DESC"
    assert condition["priceMin"] == 0
    assert condition["priceMax"] == 0
    assert condition["attributes"] == []


def test_string_array_fields_stay_strings() -> None:
    """``sizeId``/``sellerId``/``shopIds``/``skuIds`` are string arrays; ints give 400."""
    condition = (
        SearchQuery("x").size_ids(3, "154").seller_ids(741769104).shops("2JSYvWiZ").skus("sku-1")
    ).to_condition()
    assert condition["sizeId"] == ["3", "154"]
    assert condition["sellerId"] == ["741769104"]
    assert condition["shopIds"] == ["2JSYvWiZ"]
    assert condition["skuIds"] == ["sku-1"]
    for key in ("sizeId", "sellerId", "shopIds", "skuIds"):
        assert all(isinstance(v, str) for v in condition[key])


def test_id_fields_are_integers() -> None:
    condition = (
        SearchQuery("x")
        .categories(859, "100")
        .brands("3272")
        .conditions(Condition.NEW, 2)
        .shipping_payer(ShippingPayer.SELLER)
        .shipping_from(13)
        .exclude_shipping_methods(1)
    ).to_condition()
    assert condition["categoryId"] == [859, 100]
    assert condition["brandId"] == [3272]
    assert condition["itemConditionId"] == [1, 2]
    assert condition["shippingPayerId"] == [2]
    assert condition["shippingFromArea"] == [13]
    assert condition["excludeShippingMethodIds"] == [1]
    for key in ("categoryId", "brandId", "itemConditionId", "shippingPayerId"):
        assert all(isinstance(v, int) for v in condition[key])


def test_enum_fields_serialise_to_api_values() -> None:
    condition = (
        SearchQuery("x")
        .item_types(ItemType.MERCARI)
        .shipping_method(ShippingMethod.ANONYMOUS, ShippingMethod.JAPAN_POST)
        .status(Status.SOLD_OUT, Status.TRADING)
    ).to_condition()
    assert condition["itemTypes"] == ["ITEM_TYPE_MERCARI"]
    assert condition["shippingMethod"] == ["SHIPPING_METHOD_ANONYMOUS", "SHIPPING_METHOD_JAPAN_POST"]
    assert condition["status"] == ["STATUS_SOLD_OUT", "STATUS_TRADING"]


def test_sold_out_helper_matches_the_web_checkbox() -> None:
    assert set(SearchQuery("x").sold_out().to_condition()["status"]) == {
        "STATUS_SOLD_OUT",
        "STATUS_TRADING",
    }


def test_empty_status_means_everything() -> None:
    assert SearchQuery("x").status().to_condition()["status"] == []


def test_non_web_sort_combination_warns() -> None:
    with pytest.warns(UserWarning, match="not one of the five"):
        SearchQuery("x").sort(Sort.CREATED_TIME, Order.ASC)
    with pytest.warns(UserWarning):
        SearchQuery("x").sort(Sort.SCORE, Order.ASC)


@pytest.mark.parametrize(
    ("sort_by", "order_by"),
    [
        (Sort.SCORE, Order.DESC),
        (Sort.CREATED_TIME, Order.DESC),
        (Sort.PRICE, Order.ASC),
        (Sort.PRICE, Order.DESC),
        (Sort.NUM_LIKES, Order.DESC),
    ],
)
def test_web_sort_combinations_do_not_warn(sort_by: Sort, order_by: Order) -> None:
    import warnings

    with warnings.catch_warnings():
        warnings.simplefilter("error")
        SearchQuery("x").sort(sort_by, order_by)


def test_price_zero_is_unbounded_and_inverted_range_is_rejected() -> None:
    assert SearchQuery("x").price(10_000, 0).to_condition()["priceMax"] == 0
    assert SearchQuery("x").price(0, 80_000).to_condition()["priceMin"] == 0
    with pytest.raises(ValueError, match="price_min"):
        SearchQuery("x").price(80_000, 10_000)


def test_created_after_applies_the_jst_offset() -> None:
    """The server reads the value as JST, so ``+32400`` is added on the wire (01 §3.2)."""
    ts = 1_788_000_000
    condition = SearchQuery("x").created_after(ts).created_before(ts + 3600).to_condition()
    assert condition["createdAfterDate"] == str(ts + JST_OFFSET_SECONDS)
    assert condition["createdBeforeDate"] == str(ts + 3600 + JST_OFFSET_SECONDS)
    assert JST_OFFSET_SECONDS == 32_400


def test_created_after_accepts_datetime() -> None:
    when = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)
    condition = SearchQuery("x").created_after(when).to_condition()
    assert condition["createdAfterDate"] == str(int(when.timestamp()) + JST_OFFSET_SECONDS)


def test_hidden_date_keys_absent_by_default() -> None:
    condition = SearchQuery("x").to_condition()
    assert "createdAfterDate" not in condition
    assert "createdBeforeDate" not in condition


def test_extra_passes_unknown_fields_through() -> None:
    condition = SearchQuery("x").with_extra(promotionValidAt="now", createdAfterDate="1").to_condition()
    assert condition["promotionValidAt"] == "now"
    assert condition["createdAfterDate"] == "1"  # extra wins, letting users bypass the offset


def test_attribute_filters_merge_per_section() -> None:
    black = AttributeFilter("7bd3eacc", ("340258ac",))
    white = AttributeFilter("7bd3eacc", ("a167b2a8",))
    listing = AttributeFilter("d664efe3", ("3b6eac8c",))
    attributes = SearchQuery("x").attributes(black, white, listing).to_condition()["attributes"]
    assert {a["id"] for a in attributes} == {"7bd3eacc", "d664efe3"}
    color = next(a for a in attributes if a["id"] == "7bd3eacc")
    assert color["values"] == ["340258ac", "a167b2a8"]


def test_builders_return_new_objects() -> None:
    base = SearchQuery("iphone")
    narrowed = base.price(1000, 2000)
    assert base.price_min == 0
    assert narrowed.price_min == 1000
    assert base is not narrowed


def test_as_query_accepts_a_bare_keyword() -> None:
    assert as_query("iphone").keyword == "iphone"
    query = SearchQuery("x")
    assert as_query(query) is query


def test_thumbnail_type_is_not_part_of_the_search_condition() -> None:
    """``thumbnailTypes`` is a top-level body field, so the 22 keys must not change."""
    from carimer.models.enums import ThumbnailType

    query = SearchQuery("x").thumbnail_type(ThumbnailType.JPEG)
    assert set(query.to_condition()) == CAPTURE_CONDITION_KEYS
    assert query.thumbnail_types == (ThumbnailType.JPEG,)
    assert SearchQuery("x").thumbnail_types == ()
