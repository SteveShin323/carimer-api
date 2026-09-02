"""Phase 2 live checks — 6 calls (Phase 2).

Absolute counts move over time, so the assertions compare orders of magnitude and
relative sizes, as the plan requires.
"""

from __future__ import annotations

import time

import pytest

from carimer import Client, ItemType, SearchQuery, Status
from carimer.search.query import JST_OFFSET_SECONDS

from .conftest import LIVE_OPTIONS

pytestmark = [pytest.mark.live, pytest.mark.phase2]

BASE = SearchQuery("iphone 15").price(10_000, 80_000)


@pytest.fixture(scope="module")
def client() -> object:
    with Client(options=LIVE_OPTIONS) as c:
        yield c


@pytest.mark.smoke
def test_first_page_is_full_and_total_is_plausible(client: Client) -> None:
    """Call 1 — a full page of 120 and a five-figure-or-less estimate."""
    page = client.search(BASE, page_size=120)
    assert len(page.items) == 120
    assert page.approx_total is not None
    assert 1_000 < page.approx_total < 10_000, page.approx_total
    assert all(10_000 <= item.price <= 80_000 for item in page.items)
    assert all(item.status is Status.ON_SALE for item in page.items)
    assert page.next_page_token
    assert page.query_chips, "the web app shows keyword chips for this query"


def test_all_statuses_returns_more_than_on_sale_only(client: Client) -> None:
    """Call 2 — ``status=[]`` means everything, not "unset" (01 §3.2)."""
    on_sale_total = client.search(BASE, page_size=1).approx_total
    everything_total = client.search(BASE.status(), page_size=1).approx_total
    assert on_sale_total is not None and everything_total is not None
    assert everything_total > on_sale_total, (everything_total, on_sale_total)


def test_iter_pages_three_pages_without_duplicate_ids(client: Client) -> None:
    """Calls 4-6 — token walking with de-duplication."""
    pages = list(client.iter_pages(BASE, max_pages=3))
    assert len(pages) == 3
    ids = [item.id for page in pages for item in page.items]
    assert len(ids) == len(set(ids)), f"{len(ids) - len(set(ids))} duplicate ids across 3 pages"
    assert pages[-1].truncated is True  # the server still offers a next page
    assert [page.raw["meta"]["nextPageToken"] for page in pages[:2]] == ["v1:1", "v1:2"]


def test_created_after_is_sent_in_jst_and_filters_correctly() -> None:
    """Call 3 — the server reads the value as JST, so ``+32400`` goes on the wire.

    Uses its own client so the module-scoped one keeps its page budget.
    """
    since = int(time.time()) - 3600
    query = SearchQuery("iphone").created_after(since).item_types(ItemType.MERCARI)
    assert query.to_condition()["createdAfterDate"] == str(since + JST_OFFSET_SECONDS)

    with Client(options=LIVE_OPTIONS) as client:
        page = client.search(query, page_size=20)
    assert page.raw["searchCondition"]["createdAfterDate"] == str(since + JST_OFFSET_SECONDS)
    stale = [item for item in page.items if item.created and item.created.timestamp() < since]
    assert not stale, f"{len(stale)}/{len(page.items)} items older than the cutoff"


def test_thumbnail_type_jpeg_changes_the_url(client: Client) -> None:
    """Call 8 — ``thumbnailTypes: ["JPEG"]`` switches the thumbnail path (01 §3.1)."""
    from carimer import ThumbnailType

    page = client.search(BASE.thumbnail_type(ThumbnailType.JPEG), page_size=5)
    assert page.items
    urls = [url for item in page.items for url in item.thumbnails]
    assert urls, "no thumbnails returned"
    assert all("/jpeg/" in url for url in urls), urls[:2]
