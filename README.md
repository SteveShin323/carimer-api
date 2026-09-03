# carimer

An unofficial Python client for the private API behind `jp.mercari.com` (Mercari Japan),
covering what the web app can do **anonymously**: search, filter and read listings.

It supports all 16 sidebar filters. That includes the **dynamic attribute filters** —
colour, discount, authentication, listing format, refurbished and time sale — which the
existing open-source wrappers do not, along with category-tree navigation and brand lookup,
both fetched from `facets:suggest` at runtime.

## ⚠️ Before you use this

- **This is an unofficial, private API.** Mercari does not publish or document it, and it
  changes without notice. It changed twice while this package was being written on
  2026-09-02: the filter section list and two attribute display names (see
  [docs/01-api-spec.md](docs/01-api-spec.md) §4.4-4.6).
- **Using it may violate Mercari's terms of service.** That judgement, and the
  responsibility, are yours. Check the terms and the applicable law before commercial use,
  bulk collection or redistribution.
- **You can get blocked.** Cloudflare sits in front of the API. Both transports serialize
  requests at concurrency 1 and keep a 0.5 s minimum gap by default. A 403 is treated as a
  block and never retried. Lowering those defaults is not recommended.
- Anything that needs a login — likes, comments, purchases, offers, saved searches — is
  **out of scope**.
- The twelve personal fields in the seller profile response (`email`, `phone_number`,
  `current_sales` and so on) are not modelled and are stripped from `raw` as well.

## Install

Requires Python 3.12+.

```bash
pip install -e .
```

For development:

```bash
make install   # uv venv plus the dev extras
make all       # ruff, mypy --strict, unit tests
```

## Five-minute example

```python
from carimer import (
    AttributeSection, Client, Condition, Order, SearchQuery, ShippingPayer, Sort,
)

with Client() as client:
    query = (
        SearchQuery("iphone 15")
        .price(10_000, 80_000)                                  # 0 means unbounded
        .conditions(Condition.NEW, Condition.LIKE_NEW)          # 商品の状態 1 and 2
        .shipping_payer(ShippingPayer.SELLER)                   # 送料込み
        .attr(AttributeSection.COLOR, "ブラック系")               # colour, a dynamic attribute
        .attr(AttributeSection.LISTING_FORMAT, "通常出品")        # excludes auctions
        .sort(Sort.PRICE, Order.ASC)                            # 価格の安い順
    )

    page = client.search(query)
    print(page.approx_total)                                    # an estimate — see the notes below
    for item in page.items[:5]:
        print(item.price, item.name, item.id)

    # One method for personal listings and Shops products alike
    detail = client.get_detail(page.items[0])                   # Item | ShopsProduct
```

Runnable examples: [`examples/quickstart.py`](examples/quickstart.py),
[`examples/watch_new_listings.py`](examples/watch_new_listings.py),
[`examples/seller_report.py`](examples/seller_report.py).

The async client has the same names. There is deliberately no sync facade that drives an
event loop.

```python
from carimer import AsyncClient

async with AsyncClient() as client:
    page = await client.search("iphone 15")
    async for item in client.iter_items("iphone 15", max_items=300):
        ...
```

## Filter helpers

| Web UI | Helper | Notes |
|---|---|---|
| search box / 除外キーワード | `SearchQuery("kw")` / `.exclude("junk")` | |
| 価格 | `.price(min, max)` | `0` is unbounded; `min > max` raises `ValueError` |
| 販売状況 | on sale by default, `.sold_out()`, `.status()` | `.status()` with no argument means **everything** |
| 商品の状態 | `.conditions(Condition.NEW, ...)` | 1-6 |
| 配送料の負担 | `.shipping_payer(ShippingPayer.SELLER)` | |
| カテゴリー | `.categories(859)` | the current tree; walk it with `client.categories.path(859)` |
| ブランド | `.brands(3272)` | find the id with `client.facets.brands("apple")` |
| サイズ | `.sizes("洋服のサイズ", "M")` or `.size_ids("3")` | the two routes select the same set |
| 出品者 | `.item_types(ItemType.MERCARI)` | individual or Shops |
| 発送オプション | `.shipping_method(ShippingMethod.ANONYMOUS)` | |
| colour, discount, authentication, listing format, refurbished, time sale | `.attr(AttributeSection.COLOR, "ブラック系")` | display names must match exactly |
| the five sort options | `.sort(Sort.PRICE, Order.ASC)` | a combination the web does not offer warns |
| no web UI: origin, seller, storefront, time window | `.shipping_from(13)`, `.seller_ids("...")`, `.shops("...")`, `.created_after(ts)` | |
| no web UI: thumbnail format | `.thumbnail_type(ThumbnailType.JPEG)` | `WEBP` and `JPEG` only; a top-level field, so `with_extra` cannot send it |
| an unmodelled field | `.with_extra(someNewField=1)` | passed through as-is (`searchCondition` fields only) |

Values inside one section are OR-ed; different sections are AND-ed. **The API has no
negative filter** — "exclude auctions" is expressed as
`.attr(AttributeSection.LISTING_FORMAT, "通常出品")`.

If you already know an attribute's UUIDs you can skip name resolution:

```python
from carimer import AttributeFilter
query.attributes(AttributeFilter("d664efe3-ae5a-4824-b729-e789bf93aba9", ("3b6eac8c-...",)))
```

## API behaviour worth knowing

- **`approx_total` (`numFound`) is not a total.** It is capped at 15,000, changes between
  pages of the same query, and depends on the sort index. Do not compute a page count from
  it — walk with `iter_pages(max_pages=...)`. When the walk stops at the cap, the last page
  is flagged `truncated=True`.
- **Do not use one `SORT_CREATED_TIME` page to detect new listings.** It is not strictly
  ordered (39 of 120 adjacent pairs were inverted). `watch_new_listings()` combines that
  sort with an overlapping `created_after(ts)` window and walks every page in the window,
  up to `max_pages_per_cycle=50`. It advances its watermark only after a complete walk;
  hitting the cap keeps the previous watermark and logs a possible-gap warning. Retained
  IDs are pruned with the overlap window. The server reads the time value as JST, so the
  package adds 32,400 seconds on the wire and re-checks each item client-side.
- **`items/get` returns 400 for Shops products** (`ITEM_TYPE_BEYOND`). `get_detail()`
  routes on the id shape and on `kind` before sending; passing a Shops id to `get_item()`
  raises `ShopsItemError` without a request.
- **Attribute display names and the section list change.** Values are fetched from
  `facets:suggest` at runtime and only fall back to the bundled snapshot
  (`fallback_catalog.json`), with a warning, when the live lookup fails. A name missing
  from a successful lookup raises `UnknownFacetValue`, which also prevents a display name
  from being used with the wrong section. Refresh the snapshot with
  `scripts/refresh_fallback_catalog.py`.
- A 403 is treated as a block and fails immediately. Only 429, 5xx and network errors are
  retried. Numeric and HTTP-date `Retry-After` values are honored independently of the
  exponential-backoff ceiling. Values above the separate `max_retry_after=3600` default
  fail immediately instead of retrying before the server requested.

## Health check

```bash
python scripts/health_check.py --markdown     # exits 1 if a required check fails
```

Required checks (search, detail, profile, the required filter sections, the
`createdAfterDate` JST correction) are separated from optional ones (colour list, Shops
detail, auction parsing, the regular-listing filter excluding auctions, badges, desired
price), and the difference against the bundled snapshot is reported.
[`.github/workflows/api-health.yml`](.github/workflows/api-health.yml) runs it every six
hours and opens an `api-health` issue on failure, commenting on the existing one if there
is one.

**The cron only runs on the remote repository.** In a local clone the workflow never fires,
so either run the command above yourself, or trigger `API health` once from the Actions tab
via *Run workflow*.

## Tests

```bash
pytest                          # unit tests by default; live tests are deselected
make test                        # unit tests (respx mocks, no live calls)
pytest -m "live and smoke"       # live smoke set, 6 calls
pytest -m "live and phase3"      # one phase of the live suite
pytest -m "live and scenario"    # the acceptance scenarios
```

Live tests hit the real API. An explicit `-m live` expression overrides the safe default,
so the live targets continue to work. They are paced at 0.6 s and budgeted at ≤20 calls
per phase and ≤70 in total; every live session prints the actual count.

## Documentation

| Document | Contents |
|---|---|
| [docs/01-api-spec.md](docs/01-api-spec.md) | endpoints, payloads and errors — the single source of truth for API behaviour |
| [docs/02-filter-catalog.md](docs/02-filter-catalog.md) | the 16 web filters mapped onto API fields, plus the value snapshot |
| [docs/03-architecture.md](docs/03-architecture.md) | package layout and public API names |

## License

MIT — see [LICENSE](LICENSE).
