# 03 — Architecture

Python 3.12+, `httpx`, `pydantic` v2, `cryptography`. Facts about API behaviour live in
`01-api-spec.md` and that document wins any disagreement. This one is the single source of
truth for **public API names**.

## 1. Design principles

1. **Mirror the web app.** Request bodies and headers reproduce the captures in
   `01-api-spec.md`, including fields the server appears to ignore. A body that differs
   takes a different index and returns different results.
2. **Filters are data, not code.** Attribute UUIDs, the category tree and brands come from
   `facets:suggest` and the master datasets, then get cached. The only constants in code
   are the enums the API has fixed (sort, status, seller type, shipping option, item
   condition, who pays shipping) plus the seven dynamic attribute **section** ids. The
   value UUIDs from `02-filter-catalog.md` live in `fallback_catalog.json` and are used
   offline and in tests only.
3. **Parse leniently, keep the original.** Models require three fields (`id`, `name`,
   `price`); everything else is optional. Every model keeps the untouched payload in
   `raw`. Stringified numbers are cast in the parser.
4. **One result type for Shops and personal listings.** `SearchItem.kind`
   (`"mercari" | "shops"`) distinguishes them, and `get_detail()` routes before sending.
5. **Never trust the total.** Pagination is an iterator whose stop conditions are an empty
   page, an empty token or `max_pages`. Hitting the cap is reported as `truncated=True`.
6. **An I/O-free core with two transports.** The request builders (`api/`) and response
   parsers (`models/`) are pure functions. `SyncTransport` and `AsyncTransport` wrap
   `httpx.Client` and `httpx.AsyncClient` and call the same functions. There is no sync
   facade that drives an event loop — that breaks inside notebooks and other running loops.

## 2. Package layout

```
src/carimer/
  __init__.py            # public re-exports
  _version.py
  transport/
    dpop.py              # ES256 key generation and DPoP tokens (cryptography only)
    base.py              # header assembly, signing, error mapping, retry policy (no I/O)
    sync.py / asyncio.py # httpx.Client / httpx.AsyncClient wrappers, retries, min_interval
    errors.py            # exception hierarchy
  api/                   # per-endpoint request builders returning Request(method, url, params, json, headers). No I/O
    search.py            # entities:search and facets:suggest bodies, facetId encoding
    items.py             # items/get, shops products, relateditems, desiredPrice
    users.py             # get_profile, get_items, reviews, usersocialjp
    master.py            # services/master/v1/*, master/v2/datasets/*
    suggest.py           # search_index/terms
  models/                # pydantic models plus dict-to-model parsers (no I/O)
    common.py            # RawModel (keeps raw), timestamp and numeric-string helpers
    enums.py             # Sort, Order, Status, ItemType, ShippingMethod, Condition, ShippingPayer, ThumbnailType
    search.py            # SearchItem, SearchPage, Auction, QuerySuggestChip
    item.py              # Item, ItemAttribute, EmbeddedSeller, ConvertedPrice
    shops.py             # Shop, ShopsProduct, ShopsVariant
    profile.py           # Profile (personal fields excluded), SellerItem, Review, Badge
    facets.py            # Facet, FacetSection, CategoryNode, Brand, Size, SizeGroup
    misc.py              # SimilarItem, Suggestion, DesiredPriceInfo
  search/
    query.py             # SearchQuery (immutable builder) to a searchCondition dict, with type coercion
    attributes.py        # AttributeSection, AttributeFilter, AttributeResolver (display name to UUID)
    paginate.py          # iter_pages / iter_items, sync and async
    pager.py             # max_pager_id paging for the legacy seller endpoints
    monitor.py           # watch_new_listings
  catalog/
    facets_client.py     # facets:suggest wrapper
    categories.py        # loads the current tree, path() and children()
    cache.py             # in-memory TTL cache plus an optional disk layer
    fallback.py          # bundled snapshot loader
    fallback_catalog.json
  client.py              # Client / AsyncClient
scripts/
  health_check.py
  refresh_fallback_catalog.py   # dumps live facets:suggest into fallback_catalog.json
tests/
  unit/                  # respx mocks plus fixtures/*.json
  live/                  # -m live, phase markers
  fixtures/
```

## 3. Layer by layer

### 3.1 transport

- `DpopSigner(key=None)` with `sign(method, url) -> str`. `url` is the final URL including
  the query string, as the web app signs it; the server only compares the path (01 §1.2)
  but there is no reason to differ. `jwk.x`/`jwk.y` and the signature halves `r`/`s` are
  each **left-zero-padded to 32 bytes**.
- `transport/base.py`
  - Options: `user_agent`, `device_uuid` (shared by `laplaceDeviceUuid` and the DPoP
    `uuid` claim), `rotate_every: int = 0`, `min_interval: float = 0.5`,
    `proxy: str | None`, `timeout`, `max_retries=3`.
  - The five default headers: `DPoP`, `X-Platform: web`,
    `Accept: application/json, text/plain, */*`, `Accept-Language: ja`, and
    `Content-Type: application/json` for POST. Per-request headers are applied last, which
    is how `master/v2/datasets/*` replaces `Accept` with exactly `application/json`.
  - `searchSessionId` is generated once per transport and shared by search and facets;
    `rotate_session()` replaces it.
  - Response-to-exception mapping is the pure function
    `errors.from_response(status, headers, body)`.
- `sync.py` / `asyncio.py`: sending, `min_interval` (monotonic clock plus sleep in the sync
  transport, an `asyncio.Lock` in the async one, which also pins concurrency at 1), and
  retries with exponential backoff from 0.5 s to 8 s on 429, 5xx and network errors,
  honouring `Retry-After`. Other 4xx are not retried. 403 fails immediately as
  `BlockedError`.

### 3.2 errors

```
CarimerError
├─ TransportError(status, body)            # network failure or a 5xx that survived retries
├─ AuthError                               # 401 (DPoP missing or mismatched)
├─ BlockedError                            # 403 (suspected Cloudflare block, never retried)
├─ BadRequestError(code, message)          # 400 (enum/type errors, InvalidArgument, InvalidRequest, UnsupportedVersionException)
├─ NotFoundError(kind)                     # 404 (item / user / shops / master / unknown path)
├─ RateLimitedError(retry_after)           # 429 (body shape unobserved; mapped by status alone)
├─ NotAcceptableError                      # 406
├─ ShopsItemError                          # a Shops id passed to get_item(); raised before any request
├─ ParseError(field, raw)                  # a required field is missing
└─ UnknownFacetValue                       # a display name could not be resolved to a UUID
```

`errors.parse_error_body(body) -> (code, message)` handles the legacy JSON shape
(`errors[0].code`), the gRPC JSON shape (`code`, `message`) and **non-JSON** bodies (the
406 text, `404 page not found`), returning `(None, body[:200])` for the last.

### 3.3 api — request builders, no I/O

Each function returns a `Request(method, url, params, json, headers)` dataclass.

- `search.build_search_body(cond, *, page_token="", page_size=120, session_id, device_uuid,
  with_shopname=True, with_search_condition_id=False, thumbnail_types=()) -> dict` —
  the structure of 01 §3.1. `thumbnail_types` goes out as the top-level `thumbnailTypes`
  and defaults to an empty array, like the web (webp). Only `WEBP` and `JPEG` are valid.
- `search.build_facets_body(cond, facet_id, *, facet_query=None, with_selected=False,
  with_relevant=True, session_id) -> dict` — the `facetQuery` key is omitted when
  `facet_query` is None.
- `search.encode_facet_id(key, value="") -> str`: `"1" + US + b64encode(key + US + value)`
  using **standard base64 with `=` padding kept**. `decode_facet_id` is the inverse.
- `items.get_item(item_id, *, country_code=None)` — the six web include flags are fixed.
- `items.get_shops_product(product_id)`.
- `users.get_profile(user_id)` — `_user_format=profile` is always sent.
- `users.get_seller_items(seller_id, *, limit=100, status=("on_sale",), max_pager_id=None,
  exclude_archived=False)` — the default status matches the web. Ask for all three
  explicitly if you want them.
- `users.get_reviews(user_id, *, limit=100, max_pager_id=None, subject=("seller","buyer"),
  fame=("good","normal","bad"))`.
- `master.dataset(name)`: names in the `master/v2` set (`item_categories`,
  `item_category_groups`, `item_brands`, `shipping_methods`) go to
  `master/v2/datasets/{name}` with the `Accept` override; the rest (`itemConditions`,
  `itemSizes`, `itemColors`, `shippingPayers`, `shippingMethods`, `itemCategories`,
  `itemBrands`) go to `services/master/v1/{name}`. Both sets are explicit constant tuples
  and any other name raises `ValueError`.

### 3.4 search.query — `SearchQuery`

An immutable dataclass whose builder methods return new objects. It owns the search
condition only; the body is assembled by `build_search_body(q.to_condition(), …)`.

```python
q = (SearchQuery("iphone 15")
     .price(10_000, 80_000)
     .conditions(Condition.NEW, Condition.LIKE_NEW)
     .shipping_payer(ShippingPayer.SELLER)
     .attr(AttributeSection.COLOR, "ブラック系", "ホワイト系")   # several values in one section are OR-ed
     .attr(AttributeSection.LISTING_FORMAT, "通常出品")         # excludes auctions; the API has no negative filter
     .item_types(ItemType.MERCARI)
     .categories(859).brands(3272)
     .size_ids("2", "3")                                      # the legacy sizeId (str)
     .sizes("洋服のサイズ", "M")                                # the attribute route; same result set
     .created_after(ts)
     .sort(Sort.PRICE, Order.ASC))
```

- `to_condition() -> dict` always emits the 22 keys. Type rules:
  `sizeId`/`sellerId`/`shopIds`/`skuIds` are `str`;
  `categoryId`/`brandId`/`itemConditionId`/`shippingPayerId`/`shippingFromArea`/
  `excludeShippingMethodIds` are `int`; enums serialise to `.value`. `attributes` is merged
  into one `{id, values}` entry per section.
- Validation: a sort combination outside the five the web offers raises `warnings.warn`.
  `price_max != 0 and price_min > price_max` raises `ValueError` (0 means unbounded).
- `extra: dict` passes unknown fields straight through. `created_after/before(ts)` are
  dedicated methods and apply the JST `+32400` correction on serialisation; to send a raw
  value use `with_extra(createdAfterDate=…)`.
- `thumbnail_type(*types: ThumbnailType)` is a top-level body field, so it does not appear
  among the 22 keys — it rides on the query and `build_search_body` reads it. It is the one
  search option `extra` cannot express.
- Names passed to `.attr()` are resolved to UUIDs by an `AttributeResolver` at
  `to_condition()` time (the resolver is injected). An unresolvable name raises
  `UnknownFacetValue`.

### 3.5 search.attributes

- `AttributeSection` (enum): `COLOR, SIZE, DISCOUNT, APPRAISAL, LISTING_FORMAT,
  REFURBISHED, TIME_SALE` mapped to the section UUIDs of 02 §1. These seven are the only
  attribute constants in code; the health check detects a change.
- `AttributeResolver(facets_client, fallback)` with
  `resolve(section, *display_names_ja) -> AttributeFilter`. Value names must match
  `displayNamesMap.ja` **exactly** — there is no alias table, because a near miss would
  silently filter on the wrong value. Order: in-memory cache, then `facets:suggest`, then
  the fallback JSON (with a warning), then `UnknownFacetValue`.
- Sizes: `sizes(group_name_ja, *names)` resolves the group UUID and then the leaf UUIDs,
  and serialises as `attributes`.

### 3.6 search.paginate

```python
def iter_pages(client, query, *, max_pages=50, page_size=120) -> Iterator[SearchPage]
def iter_items(client, query, *, max_items=None, max_pages=50) -> Iterator[SearchItem]
```

The async twins are `aiter_pages` and `aiter_items` with the same signatures.

- Stops on `items == []`, on `nextPageToken == ""` or at `max_pages`. `iter_items`
  de-duplicates through a `seen_ids` set.
- On reaching `max_pages` the last yielded page carries `truncated=True` and a
  `logging.warning` is emitted. `truncated` describes the *walk*, not the page: a single
  `client.search()` never sets it, so the same page can arrive with `truncated=True` from
  `iter_pages(q, max_pages=1)` and `False` from `search(q)`. `SearchPage.has_next` is the
  per-page question.
- `SearchPage.approx_total` (from `numFound`) documents the 15,000 cap and the per-page
  drift in its docstring.

### 3.7 search.monitor

```python
def watch_new_listings(client, query, *, on_new, interval=60, since=None,
                       include_shops=False, max_cycles=None) -> int
```

`awatch_new_listings` is the async twin, and `on_new` may be a coroutine function there.

- First cycle: when `since is None`, the ids on the current first page seed `seen_ids` and
  `since = max(created)`, **with no callback**.
- Every cycle after that: narrow server-side with `query.created_after(since - 60)` (a
  one-minute overlap), **re-filter client-side on `created > since`**, drop ids already in
  `seen_ids`, sort by `created` descending, then call back. `since` advances to the largest
  `created` seen. `created_after(ts)` serialises `ts + 32400` because the server reads the
  value as JST (01 §3.2). The client-side re-filter is the safeguard that keeps a change in
  server behaviour from producing false positives.
- `item_types` defaults to MERCARI. Shops products are opt-in because their `created`
  moves like an update timestamp (01 §3.3).

### 3.8 catalog

- `FacetsClient`
  - `sections() -> list[FacetSection]` (facetId `""`)
  - `children(key, value="", *, facet_query=None) -> list[Facet]`
  - `category_children(cat_id)`, `category_relevant(query)` (needs a query with a keyword;
    without one it always returns nothing), `brands(name_query)`, `size_groups()`,
    `sizes(group_uuid)`, `attribute_values(section)`
  - The cache key is `(facet_id, facet_query)` only. Requests always carry an empty,
    keyword-less condition, because `selected` and `relevantFacets` vary with the condition
    and would poison the cache. `category_relevant` is never cached.
- `Categories`: loads `master/v2/datasets/item_categories` and offers `get(id)`,
  `children(id)`, `path(id) -> list[CategoryNode]`, `roots()` and `search(name)`.
  `AsyncCategories` is the awaited twin.
- `TTLCache`: in memory with a 24 h TTL. When `cache_dir` is given it also writes JSON to
  disk; off by default.

### 3.9 The client facade (public API names)

```python
class AsyncClient:
    facets: AsyncFacetsClient
    categories: AsyncCategories
    attributes: AsyncAttributeResolver
    async def search(query: SearchQuery | str, *, page_token="", page_size=120) -> SearchPage
    def iter_pages(query, *, max_pages=50) -> AsyncIterator[SearchPage]
    def iter_items(query, *, max_items=None, max_pages=50) -> AsyncIterator[SearchItem]
    async def get_item(item_id, *, country_code: str | None = None) -> Item          # a Shops id raises ShopsItemError before sending
    async def get_shops_product(product_id) -> ShopsProduct
    async def get_detail(ref: SearchItem | str) -> Item | ShopsProduct                # routes on kind, or on the id shape
    async def get_profile(user_id) -> Profile
    def iter_seller_items(seller_id, *, status=("on_sale",), max_pages=None) -> AsyncIterator[SellerItem]
    def iter_reviews(user_id, *, max_items=None) -> AsyncIterator[Review]
    async def similar_items(item_id, *, limit=15) -> list[SimilarItem]
    async def suggest_keywords(text) -> list[Suggestion]
    async def seller_badges(user_id) -> list[Badge]
    async def is_identity_verified(user_id) -> bool
    async def desired_price_info(item_id) -> DesiredPriceInfo
    async def watch_new_listings(query, *, on_new, interval=60, since=None, max_cycles=None) -> int
    async def master(name) -> dict                                                    # routing per §3.3
```

`Client` is the blocking version with the same names, returning `Iterator`.

## 4. Models

| Model | Key fields | Source |
|---|---|---|
| `SearchItem` | `id, kind, name, price:int, is_no_price, status:Status, created/updated (UTC-aware datetime), thumbnails, photos, seller_id, category_id, condition_id, shipping_payer_id, shipping_method_id, brand, size, shop, auction, raw` | 01 §3.3 |
| `SearchPage` | `items, next_page_token, prev_page_token, approx_total, truncated, query_chips, search_condition_echo, raw` | |
| `QuerySuggestChip` | `label, keyword` | `components[].querySuggest` |
| `Auction` | `auction_id, bid_deadline, total_bids, highest_bid, initial_price, state, auction_type` — one model for both the search shape (camelCase, ISO) and the detail shape (snake_case, unix) | |
| `Item` | the detail fields plus `category_path: list[CategoryNode]`, `attributes: list[ItemAttribute]`, `auction`, `converted_price`, `seller: EmbeddedSeller` | 01 §5 |
| `ShopsProduct` | `id, display_name, price, tags, sold_out, thumbnail, photos, description, shop, created/updated, variants, raw` | 01 §6 |
| `Profile` | respects the exclusion list of 01 §7.1, in the model and in `raw` | |
| `SellerItem`, `Review`, `Badge`, `SimilarItem`, `Suggestion`, `DesiredPriceInfo` | | 01 §7-8 |
| `Facet`, `FacetSection`, `CategoryNode`, `Brand`, `Size`, `SizeGroup` | | 01 §4, §9 |

- Every `datetime` is **UTC-aware**; the original unix value stays in `raw`.
- Status normalisation: search `ITEM_STATUS_ON_SALE` and detail `on_sale` both become one
  `Status` enum (`ON_SALE, TRADING, SOLD_OUT, STOP, CANCEL, UNKNOWN`).
- `Item.ui_attributes` and `Item.filterable_attributes` are different sets, because colour
  arrives with `show_on_ui: false` and `deep_facet_filterable: true` (01 §5).
- The `Suggestion` parser skips wrappers other than `MixedQuery.Query`; no other shape has
  been observed.

## 5. Test strategy

- Unit tests mock HTTP with `respx`. Fixtures are real responses with third-party personal
  data replaced by dummies. The body builders are tested for key-set equality against the
  01 §3.1 capture.
- Live tests use `-m live` plus a phase marker. Budget: ≤20 calls per phase, ≤70 in total
  including the acceptance scenarios, ≥0.5 s between requests. The smoke set
  (`-m "live and smoke"`) is 6 calls: three searches (the baseline page, the total used by
  the section check, and the detail targets), one facets root, one item detail and one
  Shops detail.
- Regressions that must stay covered: size values serialised as strings, `sellerId` as a
  string, the `master/v2` `Accept` header, Shops ids routed by `get_detail` and rejected by
  `get_item` before sending, `_user_format=profile`, `status=[]` documented as "everything",
  the warning on a non-web sort combination, the `truncated` flag at `max_pages`, and no
  retry on 403.
- `scripts/health_check.py` separates required checks (search, detail, profile, the
  required facet sections, the `createdAfterDate` JST correction) from optional ones
  (colour list, Shops detail, auction parsing, badges, desired price). An optional check
  reports `skipped` when the live data offers no target. Output is JSON plus markdown, and
  a required failure exits 1.

## 6. Operational and legal notes

- This is an unofficial API. The README states the terms-of-service risk and the chance of
  being blocked. The defaults are a 0.5 s gap and concurrency 1 (enforced by the transport
  lock).
- Personal profile fields are never stored. DPoP tokens and full bodies are kept out of the
  logs; headers are masked even at debug level.
- Attribute UUID and category changes are detected by the health check, which compares the
  live section list and colour list against the bundled snapshot and reports the difference.
