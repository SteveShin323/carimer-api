#!/usr/bin/env python
"""Regenerate ``src/carimer/catalog/fallback_catalog.json`` from the live API.

The bundled catalogue is the offline fallback used when ``facets:suggest`` cannot be
reached, plus the reference the health check diffs against (03 §1.2, §6). Values here
are a snapshot: the runtime always prefers the live lookup.

Usage: ``python scripts/refresh_fallback_catalog.py [--out PATH]``
Calls: 1 (sections) + 7 (attribute sections) + 1 per size group.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from typing import Any

from carimer.catalog.facets_client import FacetsClient
from carimer.search.attributes import AttributeSection
from carimer.transport.base import TransportOptions
from carimer.transport.sync import SyncTransport

_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_OUT = _ROOT / "src" / "carimer" / "catalog" / "fallback_catalog.json"


def build(facets: FacetsClient) -> dict[str, Any]:
    sections = facets.sections()
    catalog: dict[str, Any] = {
        "captured_at": dt.datetime.now(tz=dt.UTC).date().isoformat(),
        "sections": [
            {
                "name": section.name,
                "searchable_value": section.searchable_value,
                "is_attribute": section.is_attribute_section,
            }
            for section in sections
        ],
        "attribute_values": {},
        "size_groups": {},
    }

    for section in AttributeSection:
        values = facets.attribute_values(section.value)
        catalog["attribute_values"][section.value] = {
            facet.name: facet.searchable_value for facet in values if facet.name and facet.searchable_value
        }
        print(f"{section.name}: {len(values)} values", file=sys.stderr)

    for group in facets.size_groups():
        leaves = facets.sizes(group.value)
        catalog["size_groups"][group.value] = {
            "name": group.name,
            "values": {
                facet.name: facet.searchable_value
                for facet in leaves
                if facet.name and facet.searchable_value
            },
        }
        print(f"size group {group.name}: {len(leaves)} values", file=sys.stderr)

    return catalog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT)
    parser.add_argument("--min-interval", type=float, default=0.6)
    args = parser.parse_args()

    with SyncTransport(TransportOptions(min_interval=args.min_interval)) as transport:
        catalog = build(FacetsClient(transport))

    args.out.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sections = len(catalog["sections"])
    values = sum(len(v) for v in catalog["attribute_values"].values())
    print(f"wrote {args.out} — {sections} sections, {values} attribute values", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
