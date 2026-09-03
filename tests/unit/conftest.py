"""Fixture loading for unit tests.

The JSON files are real API responses captured by ``docs/probes/probe8_fixtures.py`` and
``probe11_detail_dump.py``, with third-party personal data replaced by deterministic
dummies: user ids (``9000000xx``), display names (``user-N``), profile photo URLs,
self-introductions, review/comment bodies and item descriptions. Listing data (item ids,
titles, prices, category ids) is kept as captured so the parsers are exercised on real
shapes.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def search_page_payload() -> dict[str, Any]:
    return load("search_page.json")


@pytest.fixture
def auction_page_payload() -> dict[str, Any]:
    return load("search_page_auction.json")


@pytest.fixture
def facets_sections_payload() -> dict[str, Any]:
    return load("facets_sections.json")


@pytest.fixture
def item_detail_payload() -> dict[str, Any]:
    return load("item_detail.json")


@pytest.fixture
def shops_product_payload() -> dict[str, Any]:
    return load("shops_product.json")


@pytest.fixture
def profile_payload() -> dict[str, Any]:
    return load("profile.json")


@pytest.fixture
def seller_items_payload() -> dict[str, Any]:
    return load("seller_items.json")


@pytest.fixture
def reviews_payload() -> dict[str, Any]:
    return load("reviews.json")


@pytest.fixture
def similar_items_payload() -> dict[str, Any]:
    return load("similar_items.json")


@pytest.fixture
def suggest_terms_payload() -> dict[str, Any]:
    return load("suggest_terms.json")


@pytest.fixture
def desired_price_payload() -> dict[str, Any]:
    return load("desired_price.json")


@pytest.fixture
def image_search_payload() -> dict[str, Any]:
    return load("image_search_page.json")


@pytest.fixture
def shop_products_payload() -> dict[str, Any]:
    return load("shop_products.json")


@pytest.fixture
def shop_details_payload() -> dict[str, Any]:
    return load("shop_details.json")


@pytest.fixture
def shop_reviews_payload() -> dict[str, Any]:
    return load("shop_reviews.json")


@pytest.fixture
def related_component_payload() -> dict[str, Any]:
    return load("related_component.json")
