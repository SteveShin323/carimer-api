"""Offline regression tests for the live health-check policy."""

from __future__ import annotations

import pytest
from scripts.health_check import HealthCheck

from carimer.models.enums import ItemType
from carimer.models.search import SearchPage
from carimer.search.attributes import AttributeSection
from carimer.search.query import SearchQuery
from carimer.transport.errors import BlockedError


class FakeClient:
    def search(self, query: SearchQuery, *, page_size: int) -> SearchPage:
        section, names = query.pending_attributes[0]
        assert section == AttributeSection.LISTING_FORMAT.value
        assert names == ("通常出品",)
        assert page_size == 20
        return SearchPage.from_api(
            {
                "meta": {"numFound": "1"},
                "items": [{"id": "m1", "name": "regular", "price": "1000"}],
            }
        )


def test_regular_listing_filter_is_optional_and_rejects_auctions() -> None:
    health = HealthCheck(FakeClient())  # type: ignore[arg-type]

    health._regular_listing_filter()

    check = health.checks[0]
    assert check.name == "regular_listing_filter"
    assert check.required is False
    assert check.status == "pass"
    assert "auctions=0" in check.detail


def _page(*items: dict[str, object]) -> SearchPage:
    return SearchPage.from_api({"meta": {"numFound": str(len(items))}, "items": list(items)})


_PERSONAL = {"id": "m1", "name": "personal", "price": "1000"}
_SHOPS = {
    "id": "2JVoP4vefPkskNLnvGbb9P",
    "name": "shop item",
    "price": "2000",
    "itemType": "ITEM_TYPE_BEYOND",
    "shop": {"id": "2JSYvWiZshopshopshopsh"},
}


class ShopsFallbackClient:
    """Counts searches so the tests can pin when the extra call is spent."""

    def __init__(self, shops_page: SearchPage | Exception) -> None:
        self.shops_page = shops_page
        self.queries: list[SearchQuery] = []

    def search(self, query: SearchQuery, *, page_size: int) -> SearchPage:
        self.queries.append(query)
        if isinstance(self.shops_page, Exception):
            raise self.shops_page
        return self.shops_page


def test_shops_page_is_reused_when_the_first_page_has_a_shops_item() -> None:
    client = ShopsFallbackClient(_page(_SHOPS))
    health = HealthCheck(client)  # type: ignore[arg-type]
    first = _page(_PERSONAL, _SHOPS)

    assert health._find_shops_page(first) is first
    assert client.queries == []


def test_shops_only_search_runs_once_when_the_first_page_has_none() -> None:
    shops = _page(_SHOPS)
    client = ShopsFallbackClient(shops)
    health = HealthCheck(client)  # type: ignore[arg-type]
    first = _page(_PERSONAL)

    assert health._find_shops_page(first) is shops
    assert health._find_shops_page(first) is shops
    assert len(client.queries) == 1
    assert client.queries[0].item_type_values == (ItemType.BEYOND,)


def test_shops_checks_skip_when_no_shops_item_exists_anywhere() -> None:
    client = ShopsFallbackClient(_page())
    health = HealthCheck(client)  # type: ignore[arg-type]

    shops = health._find_shops_page(_page(_PERSONAL))
    health._shops_detail(shops)
    health._storefront(shops)

    assert [c.status for c in health.checks] == ["skipped", "skipped"]


def test_a_failed_shops_only_search_skips_instead_of_failing() -> None:
    client = ShopsFallbackClient(RuntimeError("boom"))
    health = HealthCheck(client)  # type: ignore[arg-type]

    shops = health._find_shops_page(_page(_PERSONAL))
    health._shops_detail(shops)
    health._storefront(shops)

    assert shops is None
    assert [c.status for c in health.checks] == ["skipped", "skipped"]


def test_a_block_during_the_shops_only_search_is_not_swallowed() -> None:
    client = ShopsFallbackClient(BlockedError("403"))
    health = HealthCheck(client)  # type: ignore[arg-type]

    with pytest.raises(BlockedError):
        health._find_shops_page(_page(_PERSONAL))
