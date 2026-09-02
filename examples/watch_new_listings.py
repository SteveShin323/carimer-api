#!/usr/bin/env python
"""Watching for new listings.

`SORT_CREATED_TIME` is not strictly ordered, so the watcher narrows on
`createdAfterDate` (which the server reads as JST) and re-checks each item client-side.

Run with `python examples/watch_new_listings.py` (2 cycles, about 60 seconds).
"""

from __future__ import annotations

from carimer import Client, SearchItem, SearchQuery


def report(items: list[SearchItem]) -> None:
    for item in items:
        created = item.created.strftime("%H:%M:%S") if item.created else "?"
        print(f"[{created}] {item.price:>7,} JPY  {item.name[:40]}  https://jp.mercari.com/item/{item.id}")


def main() -> None:
    query = SearchQuery("ポケモンカード").price(0, 5_000)
    with Client() as client:
        # The first cycle only seeds state; it does not call back.
        since = client.watch_new_listings(query, on_new=report, interval=30, max_cycles=2)
        print(f"cursor for the next run: since={since}")


if __name__ == "__main__":
    main()
