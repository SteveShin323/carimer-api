"""Phase 5 live checks (Phase 5).

The watcher part only asserts that two real cycles complete without error: whether a
new listing appears in a 30-second window is not under our control.
"""

from __future__ import annotations

import pytest

from carimer import Client, ItemKind, SearchQuery

from .conftest import LIVE_OPTIONS

pytestmark = [pytest.mark.live, pytest.mark.phase5]


@pytest.fixture(scope="module")
def client() -> Client:
    with Client(options=LIVE_OPTIONS) as c:
        yield c


def test_watch_two_cycles(client: Client) -> None:
    """Calls 1-2 — ~30 s apart. Any callback payload must be genuinely new."""
    seen: list[str] = []

    def on_new(items: list) -> None:
        seen.extend(item.id for item in items)

    since = client.watch_new_listings("ポケモンカード", on_new=on_new, interval=30, max_cycles=2)
    assert since > 0
    assert len(seen) == len(set(seen)), "the same id was reported twice"


def test_suggest_keywords(client: Client) -> None:
    """Call 3."""
    suggestions = client.suggest_keywords("iphone")
    assert suggestions
    assert all(suggestion.keyword for suggestion in suggestions)


def test_similar_items_and_desired_price(client: Client) -> None:
    """Calls 4-6 — one search to get an item, then two item-scoped endpoints."""
    page = client.search(SearchQuery("iphone 15").price(10_000, 80_000), page_size=20)
    item = next(i for i in page.items if i.kind is ItemKind.MERCARI)

    similar = client.similar_items(item.id, limit=5)
    assert similar
    assert all(entry.price > 0 for entry in similar)

    info = client.desired_price_info(item.id)
    assert info.item_id == item.id
    assert info.registered_count >= 0


def test_seller_badges_and_identity(client: Client) -> None:
    """Calls 7-9 — badges can legitimately be empty; the call must still succeed."""
    page = client.search(SearchQuery("iphone 15").price(10_000, 80_000), page_size=20)
    seller_id = next(i.seller_id for i in page.items if i.seller_id)

    badges = client.seller_badges(seller_id)
    assert isinstance(badges, list)
    verified = client.is_identity_verified(seller_id)
    assert isinstance(verified, bool)
