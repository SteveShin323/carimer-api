"""Phase 3 live checks (Phase 3).

One module-scoped client so the facet cache is shared: an attribute-filtered search
otherwise pays for a facets lookup every time.

Deviation from the plan, with evidence: the plan expects ≥16 sidebar sections including
``item_types``. Between probe8 and probe9 (same day) the live section list dropped to 15
and lost 出品者 — see 01 §4.4, which also shows the ``itemTypes`` *filter* still works.
The required set is therefore the five sections observed stably, and anything else is
reported as a diff.
"""

from __future__ import annotations

import logging

import pytest

from carimer import AttributeSection, Client, SearchQuery
from carimer.catalog.fallback import fallback_sections

from .conftest import LIVE_OPTIONS

pytestmark = [pytest.mark.live, pytest.mark.phase3]

BASE = SearchQuery("iphone 15").price(10_000, 80_000)
REQUIRED_SECTIONS = {"category_id", "brand_id", "status", "item_condition_id", "price"}


@pytest.fixture(scope="module")
def client() -> Client:
    with Client(options=LIVE_OPTIONS) as c:
        yield c


@pytest.fixture(scope="module")
def base_total(client: Client) -> int:
    total = client.search(BASE, page_size=1).approx_total
    assert total is not None
    return total


@pytest.mark.smoke
def test_sections_contain_the_required_filters(client: Client, caplog: pytest.LogCaptureFixture) -> None:
    """Call 1."""
    sections = client.facets.sections()
    values = {section.searchable_value for section in sections}
    assert len(sections) >= 15, [s.name for s in sections]
    missing = REQUIRED_SECTIONS - values
    assert not missing, f"required sections missing: {sorted(missing)}"

    snapshot = {section["searchable_value"] for section in fallback_sections()}
    added, removed = values - snapshot, snapshot - values
    if added or removed:
        logging.getLogger(__name__).warning(
            "facet sections drifted from the bundled snapshot: added=%s removed=%s", added, removed
        )
    assert any(section.is_attribute_section for section in sections) or "color_id" in values


def test_brand_lookup_finds_apple(client: Client) -> None:
    """Call 2 — name search across romaji and kana."""
    brands = client.facets.brands("apple")
    assert brands, "no brand matched 'apple'"
    assert brands[0].id_as_int == 3272, [(b.name, b.searchable_value) for b in brands[:3]]


def test_category_tree_path_and_children(client: Client) -> None:
    """Calls 3-4 — the ntiers dataset plus one facet drill-down."""
    assert [node.id for node in client.categories.path(859)] == [7, 100, 859]
    children = client.facets.category_children(7)
    assert 100 in {facet.id_as_int for facet in children}


def test_relevant_categories_need_a_keyword(client: Client) -> None:
    """Call 5 — only populated when the condition carries a keyword (01 §4.1)."""
    relevant = client.facets.category_relevant(SearchQuery("iphone 15"))
    assert len(relevant) >= 1, "expected at least one relevant category for 'iphone 15'"


def test_color_attribute_filter_narrows_the_result_set(client: Client, base_total: int) -> None:
    """Calls 6-7 — resolve ブラック系, then search with it."""
    query = BASE.attr(AttributeSection.COLOR, "ブラック系")
    page = client.search(query, page_size=1)
    assert page.approx_total is not None
    share = page.approx_total / base_total
    assert 0.05 <= share <= 0.20, f"black share {share:.1%} of {base_total}"
    condition = page.raw["searchCondition"]["attributes"]
    assert condition[0]["id"] == AttributeSection.COLOR.value


def test_listing_format_selects_and_excludes_auctions(client: Client) -> None:
    """Calls 8-10 — the only way to filter auctions; ``オークション`` since 01 §4.5."""
    auctions = client.search(BASE.attr(AttributeSection.LISTING_FORMAT, "オークション"), page_size=20)
    assert auctions.items, "no auction listings found"
    assert all(item.auction is not None for item in auctions.items)

    plain = client.search(BASE.attr(AttributeSection.LISTING_FORMAT, "通常出品"), page_size=20)
    assert plain.items
    assert all(item.auction is None for item in plain.items)


def test_size_attribute_and_legacy_size_id_agree(client: Client) -> None:
    """Calls 11-14 — the two size routes must return the same count (02 §5)."""
    base = SearchQuery("ナイキ tシャツ").price(3_000, 5_000)
    by_attribute = client.search(base.sizes("洋服のサイズ", "M"), page_size=1).approx_total
    by_legacy_id = client.search(base.size_ids("3"), page_size=1).approx_total
    assert by_attribute is not None and by_legacy_id is not None
    assert by_attribute < 15_000, "at the 15,000 cap the comparison is meaningless"
    # Not exactly equal: listings appear between the two requests. Observed 4,273 vs
    # 4,268 (0.12%) on 2026-09-02, where probe6 had seen 4,266 for both.
    drift = abs(by_attribute - by_legacy_id) / max(by_attribute, by_legacy_id)
    assert drift < 0.01, (by_attribute, by_legacy_id, drift)
