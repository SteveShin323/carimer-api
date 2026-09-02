"""Phase 2: search response parsing against live-captured fixtures (01 §3.3)."""

from __future__ import annotations

import copy
from datetime import UTC
from typing import Any

import pytest

from carimer.models.enums import ItemKind, Status
from carimer.models.search import Auction, SearchItem, SearchPage, is_mercari_item_id
from carimer.transport.errors import ParseError


def test_page_metadata(search_page_payload: dict[str, Any]) -> None:
    page = SearchPage.from_api(search_page_payload)
    assert page.items
    assert page.next_page_token == "v1:1"
    assert page.prev_page_token == ""
    assert page.approx_total is not None and page.approx_total > 0
    assert page.truncated is False
    assert page.search_condition_echo["keyword"] == "iphone 15"
    assert page.raw == search_page_payload  # pydantic copies on validation; content is preserved


def test_personal_listing_is_parsed(search_page_payload: dict[str, Any]) -> None:
    page = SearchPage.from_api(search_page_payload)
    item = next(i for i in page.items if i.kind is ItemKind.MERCARI)
    assert item.id.startswith("m")
    assert item.price > 0
    assert item.status is Status.ON_SALE
    assert item.seller_id and item.seller_id != "0"
    assert item.category_id == 859
    assert item.shipping_payer_id in (1, 2)
    assert item.created is not None and item.created.tzinfo is UTC
    assert item.thumbnails and item.thumbnails[0].startswith("https://")
    assert item.is_shops is False
    assert item.sold_out is False


def test_shops_item_is_detected_and_zero_ids_are_dropped(search_page_payload: dict[str, Any]) -> None:
    """``ITEM_TYPE_BEYOND`` → ``kind == "shops"``; its seller-side ids come back as "0"."""
    page = SearchPage.from_api(search_page_payload)
    item = next(i for i in page.items if i.kind is ItemKind.SHOPS)
    assert item.raw["sellerId"] == "0"
    assert item.seller_id is None
    assert item.shipping_payer_id is None
    assert item.shipping_method_id is None
    assert item.is_shops is True
    assert not is_mercari_item_id(item.id)


def test_query_suggest_chips(search_page_payload: dict[str, Any]) -> None:
    page = SearchPage.from_api(search_page_payload)
    keywords = [chip.keyword for chip in page.query_chips]
    assert keywords, "the capture contains a querySuggest row"
    assert all(chip.label for chip in page.query_chips)


def test_auction_from_search_is_normalised(auction_page_payload: dict[str, Any]) -> None:
    page = SearchPage.from_api(auction_page_payload)
    item = page.items[0]
    assert item.auction is not None
    auction = item.auction
    assert auction.bid_deadline is not None and auction.bid_deadline.tzinfo is UTC
    assert auction.total_bids is not None and auction.total_bids >= 0
    assert auction.highest_bid is not None and auction.highest_bid > 0
    assert auction.initial_price is not None


def test_auction_detail_and_search_shapes_agree() -> None:
    """``auction`` (camelCase, ISO) and ``auction_info`` (snake_case, unix) must match."""
    from_search = Auction.from_search(
        {
            "id": "a1",
            "bidDeadline": "2026-09-02T11:39:00Z",
            "totalBid": "21",
            "highestBid": "62100",
            "initialPrice": "60000",
        }
    )
    from_detail = Auction.from_detail(
        {
            "id": "a1",
            "expected_end_time": 1_788_349_140,
            "total_bids": 21,
            "highest_bid": 62100,
            "initial_price": 60000,
            "state": "STATE_ONGOING",
            "auction_type": "AUCTION_TYPE_NORMAL",
        }
    )
    assert from_search is not None and from_detail is not None
    assert from_search.bid_deadline == from_detail.bid_deadline
    assert (from_search.total_bids, from_search.highest_bid, from_search.initial_price) == (
        from_detail.total_bids,
        from_detail.highest_bid,
        from_detail.initial_price,
    )
    assert from_detail.state == "STATE_ONGOING"


def test_no_auction_is_none(search_page_payload: dict[str, Any]) -> None:
    page = SearchPage.from_api(search_page_payload)
    assert all(item.auction is None for item in page.items)


def test_is_no_price_flag(search_page_payload: dict[str, Any]) -> None:
    """No live sample was found (probe7), so the flag is exercised on a doctored copy."""
    payload = copy.deepcopy(search_page_payload["items"][0])
    payload["isNoPrice"] = True
    payload["price"] = "9999999"
    item = SearchItem.from_api(payload)
    assert item.is_no_price is True
    assert item.price == 9_999_999


def test_status_spellings_normalise() -> None:
    assert Status.parse("ITEM_STATUS_SOLD_OUT") is Status.SOLD_OUT
    assert Status.parse("sold_out") is Status.SOLD_OUT
    assert Status.parse("STATUS_ON_SALE") is Status.ON_SALE
    assert Status.parse("") is Status.UNKNOWN
    assert Status.parse(None) is Status.UNKNOWN
    assert Status.parse("something_new") is Status.UNKNOWN
    assert Status.ON_SALE.request_value == "STATUS_ON_SALE"


def test_sold_out_is_not_inverted() -> None:
    """marvinody/mercari computes ``soldOut = status != SOLD_OUT``; that bug stays fixed."""
    base = {"id": "m1", "name": "x", "price": "100", "itemType": "ITEM_TYPE_MERCARI"}
    assert SearchItem.from_api({**base, "status": "ITEM_STATUS_SOLD_OUT"}).sold_out is True
    assert SearchItem.from_api({**base, "status": "ITEM_STATUS_ON_SALE"}).sold_out is False


@pytest.mark.parametrize("missing", ["id", "name", "price"])
def test_required_fields_raise_parse_error(missing: str) -> None:
    payload = {"id": "m1", "name": "x", "price": "100"}
    del payload[missing]
    with pytest.raises(ParseError) as excinfo:
        SearchItem.from_api(payload)
    assert excinfo.value.field == missing


def test_unknown_fields_are_kept_in_raw_and_unknown_extras_ignored() -> None:
    payload = {"id": "m1", "name": "x", "price": "100", "brandNewField": {"a": 1}}
    item = SearchItem.from_api(payload)
    assert item.raw["brandNewField"] == {"a": 1}


def test_kind_falls_back_to_the_id_shape_when_item_type_is_absent() -> None:
    assert SearchItem.from_api({"id": "m77574104522", "name": "a", "price": "1"}).kind is ItemKind.MERCARI
    assert SearchItem.from_api({"id": "2JVoP4vefPkskNLnvGbb9P", "name": "a", "price": "1"}).kind is (
        ItemKind.SHOPS
    )


def test_empty_page_parses() -> None:
    page = SearchPage.from_api({"meta": {"numFound": "0", "nextPageToken": ""}, "items": []})
    assert page.items == []
    assert page.approx_total == 0
    assert page.has_next is False
