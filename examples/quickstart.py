#!/usr/bin/env python
"""The five-minute example from the README: search, filter and read a listing.

Run with `python examples/quickstart.py` (5 live API calls).
"""

from __future__ import annotations

from carimer import (
    AttributeSection,
    Client,
    Condition,
    Order,
    SearchQuery,
    ShippingPayer,
    Sort,
)


def main() -> None:
    with Client() as client:
        # 1) Keyword, price, condition, who pays shipping, colour, no auctions,
        #    cheapest first.
        query = (
            SearchQuery("iphone 15")
            .price(10_000, 80_000)
            .conditions(Condition.NEW, Condition.LIKE_NEW)
            .shipping_payer(ShippingPayer.SELLER)
            .attr(AttributeSection.COLOR, "ブラック系")
            .attr(AttributeSection.LISTING_FORMAT, "通常出品")  # the API has no negative filter
            .sort(Sort.PRICE, Order.ASC)
        )
        page = client.search(query, page_size=20)
        print(f"about {page.approx_total} results (capped at 15,000 and it drifts per page)")
        for item in page.items[:5]:
            print(f"  {item.price:>7,} JPY  {item.name[:40]}  {item.id}")

        # 2) Browsing a category with no keyword at all.
        browse = SearchQuery().categories(859).price(0, 30_000).sort(Sort.CREATED_TIME)
        newest = client.search(browse, page_size=5)
        print(f"\nsmartphones under 30,000 JPY, newest first: {len(newest.items)} shown")

        # 3) Detail: the same method for personal listings and Shops products.
        first = page.items[0]
        detail = client.get_detail(first)
        print(f"\n{first.kind.value} detail: {type(detail).__name__} / {detail.price:,} JPY")

        # 4) Category path and brand lookup.
        print("path:", " > ".join(node.name for node in client.categories.path(859)))
        apple = client.facets.brands("apple")[0]
        print(f"brand: {apple.name} = {apple.id_as_int}")


if __name__ == "__main__":
    main()
