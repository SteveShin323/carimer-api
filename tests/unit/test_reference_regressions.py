"""The five bugs found in the reference wrappers, kept fixed (03 §5).

Each is reachable through the public API, so a refactor that reintroduces one
fails here rather than in production.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from carimer import Client, ShopsItemError, TransportOptions
from carimer.api import master as master_api
from carimer.models.search import SearchItem
from carimer.search.query import SearchQuery
from carimer.transport.base import BASE_URL
from carimer.transport.errors import NotAcceptableError

FAST = TransportOptions(min_interval=0)


def test_size_filter_serialises_as_strings() -> None:
    """take-kun/mercapi sends ``sizes: List[int]`` → 400 (01 §3.2).

    ``sizeId`` is a string array; so are ``sellerId``, ``shopIds`` and ``skuIds``.
    """
    condition = SearchQuery("x").size_ids(3).seller_ids(741769104).shops(123).skus(9).to_condition()
    assert condition["sizeId"] == ["3"]
    assert condition["sellerId"] == ["741769104"]
    assert condition["shopIds"] == ["123"]
    assert condition["skuIds"] == ["9"]
    for key in ("sizeId", "sellerId", "shopIds", "skuIds"):
        assert all(isinstance(value, str) for value in condition[key])


def test_master_v2_sends_the_exact_accept_header() -> None:
    """mercapi-node's ``getMasterData`` gets 406 because fetch defaults to ``*/*`` (01 §9)."""
    request = master_api.dataset("item_categories")
    assert request.headers["Accept"] == "application/json"

    url = f"{BASE_URL}/master/v2/datasets/item_categories"
    with respx.mock as mock:
        route = mock.get(url).mock(return_value=httpx.Response(200, json={"itemCategories": []}))
        with Client(options=FAST) as client:
            client.master("item_categories")
    assert route.calls[0].request.headers["accept"] == "application/json"

    # And a 406 is surfaced as such rather than as a JSON parse error.
    with respx.mock as mock:
        mock.get(url).mock(return_value=httpx.Response(406, text="no accepted candidate variant"))
        with Client(options=FAST) as client, pytest.raises(NotAcceptableError):
            client.master("item_categories")


def test_sold_out_is_not_inverted() -> None:
    """marvinody/mercari computes ``soldOut = status != ITEM_STATUS_SOLD_OUT``."""
    base = {"id": "m1", "name": "x", "price": "100", "itemType": "ITEM_TYPE_MERCARI"}
    assert SearchItem.from_api({**base, "status": "ITEM_STATUS_SOLD_OUT"}).sold_out is True
    assert SearchItem.from_api({**base, "status": "ITEM_STATUS_ON_SALE"}).sold_out is False
    assert SearchItem.from_api({**base, "status": "ITEM_STATUS_TRADING"}).sold_out is False


def test_shops_id_never_reaches_items_get() -> None:
    """mercapi's ``full_item()`` passes Shops ids to ``items/get`` and gets 400 (01 §5)."""
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE_URL}/items/get")
        with Client(options=FAST) as client, pytest.raises(ShopsItemError):
            client.get_item("2JVoP4vefPkskNLnvGbb9P")
    assert route.call_count == 0


def test_profile_always_sends_user_format_profile() -> None:
    """Without it ``created``/``num_sell_items`` are 0 (mercapi-node 0.2.0 fix, probe11)."""
    from carimer.api import users as users_api

    request = users_api.get_profile("1")
    assert request.params is not None
    assert request.params["_user_format"] == "profile"
