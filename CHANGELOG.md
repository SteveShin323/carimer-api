# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/).

## [0.1.1] — 2026-09-02

### Changed

- **`thumbnailTypes` is now exposed.** 0.1.0 only established that the enum accepts
  exactly two values, `WEBP` and `JPEG` (01 §3.1), without offering them through the public
  API. They are now reachable through the `ThumbnailType` enum and
  `SearchQuery.thumbnail_type()`. Because it is a top-level body field rather than part of
  `searchCondition`, `build_search_body` and `search_request` take a `thumbnail_types`
  argument and both clients forward whatever the query carries. The default stays the empty
  array the web sends (webp); asking for `JPEG` switches the `thumbnails` URL to
  `/thumb/item/jpeg/…`, confirmed live.
- **Live-call budget corrected.** The cumulative cap for `pytest -m live` moved from 60 to
  **70 including the acceptance scenarios**. The measured total for 0.1.0 was 64, and the
  scenario suite (16 calls) had never been in the budget table.
  `tests/live/conftest.py` now holds `MAX_CALLS_PER_PHASE` and `MAX_CALLS_TOTAL` as
  constants, and every live session prints the measured count against the budget.

### Documentation

- The health-check section of the README now says that the cron only runs on the remote
  repository.

### Known limitations

- Whether app-only filters exist could not be verified: no device was available to capture
  app traffic. Only `shippingFromArea`, which is confirmed, is exposed.
- What the web 「すべて」 checkbox puts in the request body remains an inference — the body
  could not be captured. The URL behaviour is confirmed (`status=on_sale` when
  「販売中のみ表示」 is on, no parameter for 「すべて」), and so is the API-side meaning of
  `status: []` (everything).

## [0.1.0] — 2026-09-02

First release. Reproduces what `jp.mercari.com` offers anonymously.

### Added

- **Transport**: ES256 DPoP signing with `cryptography` alone (`jwk.x/y` and `r`/`s`
  padded to 32 bytes), the same five headers the web app sends, a minimum gap between
  requests (0.5 s by default) with concurrency 1, exponential backoff limited to 429, 5xx
  and network errors, and 403 failing immediately as `BlockedError`. Key rotation is
  available through `rotate_every`.
- **Sync and async**: `Client` and `AsyncClient` expose the same names. Request builders
  and response parsers are I/O-free pure functions; only the transport differs. There is no
  sync facade driving an event loop.
- **Search**: the immutable `SearchQuery` builder always serialises all 22
  `searchCondition` keys. It enforces the type rules (`sizeId`, `sellerId`, `shopIds` and
  `skuIds` are strings, id fields are integers), warns on sort combinations the web does not
  offer, passes unmodelled fields through `with_extra()`, and applies the JST correction
  (+32,400 s) in `created_after/before()`.
- **Dynamic attribute filters**: `.attr(AttributeSection.COLOR, "ブラック系")` covers
  colour, discount, authentication, listing format, refurbished, time sale and size. Value
  UUIDs come from `facets:suggest` and are cached for 24 hours, falling back to the bundled
  snapshot with a warning.
- **Facets and categories**: `FacetsClient` (sections, child values, brand name search,
  suggested categories, size groups) and `Categories` (`path`, `children`, `roots`,
  `search` over the current 8,784-node tree).
- **Pagination**: `iter_pages` and `iter_items` stop on an empty page, an empty token or
  `max_pages`, and de-duplicate by id. `numFound` is surfaced as `approx_total`, and
  reaching the cap is reported as `truncated`.
- **Detail, seller and neighbourhood endpoints**: `get_item`, `get_shops_product`,
  `get_detail` (which routes before sending), `get_profile`, `iter_seller_items` and
  `iter_reviews` (both paging through `max_pager_id`), `similar_items`, `suggest_keywords`,
  `seller_badges`, `is_identity_verified`, `desired_price_info`, and `master` with the v1
  and v2 routing and `Accept` handling.
- **New-listing watcher**: `watch_new_listings()` seeds on the first cycle, then queries a
  window that overlaps by one minute, re-checks `created` client-side and de-duplicates by
  id. Shops products are excluded by default.
- **Models**: pydantic v2. Only `id`, `name` and `price` are required; everything else is
  optional, and every model keeps the untouched payload in `raw`. The spelling differences
  between search and detail (`ITEM_STATUS_ON_SALE` versus `on_sale`, camelCase versus
  snake_case, stringified numbers versus real ones) are normalised into one model.
- **Operations**: `scripts/health_check.py` (required and optional checks separated, JSON
  and markdown output, exit 1 on a required failure), a six-hourly cron workflow, and
  `scripts/refresh_fallback_catalog.py`.

### Fixed

Bugs the reference wrappers have, which this package does not:

- Size filters returning 400 — `sizeId` is serialised as an array of strings
  (take-kun/mercapi).
- Master data returning 406 — `master/v2/datasets/*` gets exactly
  `Accept: application/json` (zhu-kai/mercapi-node).
- An inverted `soldOut` check (marvinody/mercari).
- Shops product detail returning 400 — `get_detail()` routes before sending
  (take-kun/mercapi).
- A missing `_user_format=profile`, which makes `created` and `num_sell_items` come back as
  0 (mercapi-node 0.2.0).

Each has a regression test in `tests/unit/test_reference_regressions.py`.

### Known limitations

- `numFound` is not a total (capped at 15,000, and it drifts between pages).
- The filter section list and attribute display names change without notice. Name
  resolution is exact-match only.
- Anything requiring a login is out of scope.
- `shippingFromArea` is confirmed for all of 1-47 as JIS X 0401 codes; there is no
  dedicated master endpoint.
- `thumbnailTypes` values were confirmed but not exposed (added in 0.1.1).
- The two limitations listed under 0.1.1 apply to this version as well.
