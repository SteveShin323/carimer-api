"""Offline regression tests for the live health-check policy."""

from __future__ import annotations

from scripts.health_check import HealthCheck

from carimer.models.search import SearchPage
from carimer.search.attributes import AttributeSection
from carimer.search.query import SearchQuery


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
