#!/usr/bin/env python
"""A seller summary: profile, listings and reviews, both paged.

Run with `python examples/seller_report.py [seller_id]` (4-6 live API calls).
"""

from __future__ import annotations

import sys

from carimer import Client, SearchQuery


def main() -> None:
    with Client() as client:
        if len(sys.argv) > 1:
            seller_id = sys.argv[1]
        else:
            page = client.search(SearchQuery("iphone 15").price(10_000, 80_000), page_size=20)
            seller_id = next(item.seller_id for item in page.items if item.seller_id)
            print(f"picked a seller id out of the search results: {seller_id}")

        profile = client.get_profile(seller_id)
        print(f"{profile.name} · {profile.num_sell_items} listings · {profile.num_ratings} ratings")
        print(
            f"joined {profile.created:%Y-%m-%d} · identity verified: {client.is_identity_verified(seller_id)}"
        )

        print("\non sale (up to 2 pages):")
        for item in client.iter_seller_items(seller_id, limit=20, max_pages=2, status=("on_sale",)):
            print(f"  {item.price:>8,} JPY  {item.name[:40]}")

        print("\nreviews (up to 20):")
        for review in client.iter_reviews(seller_id, limit=20, max_items=20):
            print(f"  [{review.fame}] {(review.message or '')[:50]}")


if __name__ == "__main__":
    main()
