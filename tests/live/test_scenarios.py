"""Acceptance scenarios, run against the live API.

These are the end-to-end criteria, so they use the public facade only — no internal
helpers — and they check the shape of the data rather than exact counts, which move.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from carimer import (
    AttributeSection,
    Client,
    Condition,
    ItemKind,
    Order,
    SearchQuery,
    ShippingPayer,
    Sort,
)
from carimer.models.item import Item
from carimer.models.shops import ShopsProduct

from .conftest import LIVE_OPTIONS

pytestmark = [pytest.mark.live, pytest.mark.phase6, pytest.mark.scenario]

BASELINE_PATH = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "web_baseline.json"


@pytest.fixture(scope="module")
def client() -> Client:
    with Client(options=LIVE_OPTIONS) as c:
        yield c


@pytest.fixture(scope="module")
def baseline() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_scenario_1_full_filter_stack(client: Client, baseline: dict) -> None:
    """iphone 15 / 10,000-80,000 / condition 1·2 / seller pays / black / no auctions.

    ``approx_total`` is compared against the count read off the web UI on 2026-09-02
    (``tests/fixtures/web_baseline.json``), the only independent reference: the web search
    page displays no total, so that number is a manual item count.
    """
    query = (
        SearchQuery("iphone 15")
        .price(10_000, 80_000)
        .conditions(Condition.NEW, Condition.LIKE_NEW)
        .shipping_payer(ShippingPayer.SELLER)
        .attr(AttributeSection.COLOR, "ブラック系")
        .attr(AttributeSection.LISTING_FORMAT, "通常出品")
        .sort(Sort.PRICE, Order.ASC)
    )
    page = client.search(query, page_size=120)

    assert page.items, "no results for the scenario filter stack"
    assert all(10_000 <= item.price <= 80_000 for item in page.items)
    assert all(item.auction is None for item in page.items)
    prices = [item.price for item in page.items]
    assert prices == sorted(prices), "SORT_PRICE + ORDER_ASC is not ordered"

    web_total = baseline["web_result_count"]
    assert page.approx_total is not None
    ratio = page.approx_total / web_total
    assert 0.5 <= ratio <= 1.5, (
        f"approx_total {page.approx_total} vs web baseline {web_total} "
        f"({baseline['captured_at']}) = {ratio:.2f}x, outside ±50%"
    )


def test_scenario_2_category_browse_and_relevance(client: Client) -> None:
    """Keyword-less browsing plus the two category facet lookups."""
    page = client.search(SearchQuery().categories(100), page_size=30)
    assert page.items, "category-only browse returned nothing"
    assert all(item.category_id for item in page.items)

    children = client.facets.category_children(100)
    assert 859 in {facet.id_as_int for facet in children}

    relevant = client.facets.category_relevant(SearchQuery("iphone 15"))
    assert len(relevant) >= 1


def test_scenario_3_brand_lookup_then_filter(client: Client) -> None:
    brands = client.facets.brands("apple")
    assert brands and brands[0].id_as_int == 3272
    brand_id = brands[0].id_as_int
    assert brand_id is not None

    page = client.search(SearchQuery("iphone").brands(brand_id), page_size=30)
    assert page.items
    with_brand = [item for item in page.items if item.brand]
    assert with_brand, "no result carried a brand"
    assert all(item.brand and item.brand.id == 3272 for item in with_brand)


def test_scenario_4_one_detail_call_for_both_kinds(client: Client) -> None:
    page = client.search(SearchQuery("iphone 15").price(10_000, 80_000), page_size=120)
    personal = next(item for item in page.items if item.kind is ItemKind.MERCARI)
    shops = next((item for item in page.items if item.kind is ItemKind.SHOPS), None)
    if shops is None:
        pytest.skip("no Shops item on the first page of 120 right now")

    assert isinstance(client.get_detail(personal), Item)
    assert isinstance(client.get_detail(shops), ShopsProduct)


def test_scenario_5_watcher_runs_two_cycles(client: Client) -> None:
    """The de-duplication itself is covered by the fake-clock unit tests."""
    reported: list[str] = []
    since = client.watch_new_listings(
        SearchQuery("ポケモンカード"),
        on_new=lambda items: reported.extend(item.id for item in items),
        interval=30,
        max_cycles=2,
    )
    assert since > 0
    assert len(reported) == len(set(reported))


def test_scenario_6_seller_items_and_reviews_paging(client: Client) -> None:
    page = client.search(SearchQuery("iphone 15").price(10_000, 80_000), page_size=30)
    seller_id = next(item.seller_id for item in page.items if item.seller_id)

    items = list(client.iter_seller_items(seller_id, status=("on_sale",), limit=30, max_pages=3))
    ids = [item.id for item in items]
    assert ids
    assert len(ids) == len(set(ids))
    assert all(item.status.value == "on_sale" for item in items)

    reviews = list(client.iter_reviews(seller_id, limit=50, max_items=100))
    assert reviews
    assert len(reviews) <= 100
