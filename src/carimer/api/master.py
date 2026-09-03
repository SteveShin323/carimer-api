"""Master-data request builders (01 §9, 03 §3.3).

Two families live under different prefixes and only one of them cares about ``Accept``:

* ``master/v2/datasets/*`` — the current (ntiers) tree. Requires exactly
  ``Accept: application/json``; anything else answers 406, which is why
  mercapi-node's ``getMasterData`` is broken today.
* ``services/master/v1/*`` — small reference lists (conditions, sizes, colors …).
"""

from __future__ import annotations

from typing import Final

from carimer.transport.base import BASE_URL, Request

__all__ = ["MASTER_NAMES", "V1_DATASETS", "V2_DATASETS", "dataset"]

V2_DATASETS: Final = (
    "item_categories",
    "item_category_groups",
    "item_brands",
    "shipping_methods",
)

V1_DATASETS: Final = (
    "itemConditions",
    "itemSizes",
    "itemColors",
    "shippingPayers",
    "shippingMethods",
    "itemCategories",
    "itemBrands",
    # `{"areas": [{"id": "1", "name": "北海道"}, ...], "nextPageToken": ""}` — the names
    # behind `SearchQuery.shipping_from()`, which has no web UI to read them from.
    "shippingFromAreas",
)

MASTER_NAMES: Final = V2_DATASETS + V1_DATASETS


def dataset(name: str) -> Request:
    """Route a master-data name to its endpoint.

    Unknown names raise ``ValueError`` rather than producing a request that would 404.
    """
    if name in V2_DATASETS:
        return Request(
            "GET",
            f"{BASE_URL}/master/v2/datasets/{name}",
            headers={"Accept": "application/json"},
        )
    if name in V1_DATASETS:
        return Request("GET", f"{BASE_URL}/services/master/v1/{name}")
    raise ValueError(f"unknown master dataset {name!r}; expected one of {', '.join(MASTER_NAMES)}")
