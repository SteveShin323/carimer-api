"""Phase 4 live checks (Phase 4).

One search seeds every other call, so the targets are real and current.
"""

from __future__ import annotations

import pytest

from carimer import Client, ItemKind, ItemType, SearchQuery, ShopsItemError
from carimer.models.item import Item
from carimer.models.shops import ShopsProduct
from carimer.transport.errors import NotFoundError

from .conftest import LIVE_OPTIONS

pytestmark = [pytest.mark.live, pytest.mark.phase4]


@pytest.fixture(scope="module")
def client() -> Client:
    with Client(options=LIVE_OPTIONS) as c:
        yield c


@pytest.fixture(scope="module")
def targets(client: Client) -> dict[str, str]:
    """Calls 1-2 — one personal listing and one Shops product, plus a seller id.

    The first page does not always contain a Shops item, so it is fetched with an
    ``itemTypes`` filter when missing.
    """
    page = client.search(SearchQuery("iphone 15").price(10_000, 80_000), page_size=60)
    personal = next(item for item in page.items if item.kind is ItemKind.MERCARI)
    shops = next((item for item in page.items if item.kind is ItemKind.SHOPS), None)
    if shops is None:
        shops_page = client.search(SearchQuery("iphone 15").item_types(ItemType.BEYOND), page_size=5)
        shops = shops_page.items[0]
    assert personal.seller_id
    return {"item": personal.id, "shops": shops.id, "seller": personal.seller_id}


@pytest.mark.smoke
def test_get_detail_routes_both_kinds(client: Client, targets: dict[str, str]) -> None:
    """Calls 3-4 — one method, two endpoints."""
    personal = client.get_detail(targets["item"])
    shops = client.get_detail(targets["shops"])
    assert isinstance(personal, Item)
    assert personal.id == targets["item"]
    assert personal.description is not None
    assert isinstance(shops, ShopsProduct)
    assert shops.id == targets["shops"]
    assert shops.display_name


def test_get_item_refuses_a_shops_id_locally(client: Client, targets: dict[str, str]) -> None:
    """No call — the guard runs before the request (01 §5)."""
    with pytest.raises(ShopsItemError):
        client.get_item(targets["shops"])


def test_converted_price(client: Client, targets: dict[str, str]) -> None:
    """Call 5."""
    item = client.get_item(targets["item"], country_code="US")
    assert item.converted_price is not None
    assert item.converted_price.currency_code == "USD"
    assert item.converted_price.price > 0


def test_unknown_item_id_is_not_found(client: Client) -> None:
    """Call 6."""
    with pytest.raises(NotFoundError):
        client.get_item("m00000000000")


def test_profile_needs_user_format(client: Client, targets: dict[str, str]) -> None:
    """Call 7 — ``created`` would be 0 without ``_user_format=profile``."""
    profile = client.get_profile(targets["seller"])
    assert profile.id == targets["seller"]
    assert profile.created is not None
    assert profile.num_sell_items is not None and profile.num_sell_items >= 0
    for field in ("email", "phone_number", "current_sales", "current_point"):
        assert field not in profile.raw


def test_seller_items_pages_without_overlap(client: Client, targets: dict[str, str]) -> None:
    """Calls 8-10 — ``max_pager_id`` paging over a small limit."""
    items = list(client.iter_seller_items(targets["seller"], limit=5, max_pages=3, status=("on_sale",)))
    ids = [item.id for item in items]
    assert ids, "seller has no on-sale items"
    assert len(ids) == len(set(ids)), "pages overlapped"
    assert all(item.status.value == "on_sale" for item in items)


def test_reviews_page_without_overlap(client: Client, targets: dict[str, str]) -> None:
    """Calls 11-12 — up to 100 reviews across two pages."""
    reviews = list(client.iter_reviews(targets["seller"], limit=50, max_items=100, max_pages=2))
    assert reviews, "seller has no reviews"
    keys = [(review.pager_id, review.created) for review in reviews]
    assert len(keys) == len(set(keys)), "pages overlapped"


def test_master_datasets(client: Client) -> None:
    """Calls 13-14 — the v2 route needs the exact Accept header, v1 does not."""
    categories = client.master("item_categories")
    assert len(categories["itemCategories"]) > 1_000

    conditions = client.master("itemConditions")
    assert len(conditions["conditions"]) == 6, conditions["conditions"]
