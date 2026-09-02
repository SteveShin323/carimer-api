# 01 — Mercari (JP) private API specification (verified live 2026-09-02)

Everything here was confirmed by sending real requests to `https://api.mercari.jp`, except
where marked "assumed". Web-app traffic was captured by hooking `fetch`/`XHR` on the
`jp.mercari.com` search and item pages.

This document is the single source of truth for API behaviour. Where another document
disagrees, this one wins.

## 1. Common

### 1.1 Base URL and headers

- Base URL: `https://api.mercari.jp`
- Required headers

| Header | Value | If missing |
|---|---|---|
| `DPoP` | the JWT from §1.2 | 401 `{"code":16,"message":"unauthorized: missing auth token"}` |
| `X-Platform` | `web` | removing it or sending another value (`ios`) gives 400 `UnsupportedVersionException` (both confirmed) |

- The web app also sends: `Accept: application/json, text/plain, */*`,
  `Accept-Language: ja`, `Content-Type: application/json` (POST), and a browser
  User-Agent. The UA is not inspected (`python-requests` also returns 200).
- **The five headers this wrapper sends**: `DPoP`, `X-Platform: web`, `Accept`,
  `Accept-Language`, `Content-Type` (POST). The UA is optional.
- Only `master/v2/datasets/*` requires `Accept: application/json` to match exactly (§9).

### 1.2 The DPoP token

An ES256 JWS built per request. Unlike standard DPoP, the server neither registers keys
nor tracks their reuse.

```
header  = {"typ":"dpop+jwt","alg":"ES256","jwk":{"crv":"P-256","kty":"EC","x":<b64url>,"y":<b64url>}}
payload = {"iat":<unix seconds>,"jti":<uuid4>,"htu":<request URL>,"htm":<"GET"|"POST">,"uuid":<device uuid, optional>}
token   = b64url(header) + "." + b64url(payload) + "." + b64url(r||s)
```

`r` and `s` are each left-zero-padded to 32 bytes, and so are `jwk.x` and `jwk.y`. An
unpadded big-endian integer is 31 bytes roughly one time in 256, which the server rejects.

Confirmed rules

| Item | Result |
|---|---|
| `htu` mismatch | 401 `unauthorized: invalid token` |
| `htm` mismatch | 401, same body |
| query string in `htu` | the server **compares the path only and ignores the query**: signing `?id=OTHER` for a request to `items/get?id=A` still returns 200, and so does signing with no query at all. The wrapper signs the full final URL, as the web app does |
| `iat` | one day in the past and ten minutes in the future both return 200; not validated |
| `jti` | a non-uuid string also returns 200 |
| `uuid` claim | omitting it returns 200 |
| key reuse | a fresh key per request is fine, so is one key for a long session, so is replaying the same token three times |

### 1.3 Two families of error response

| Family | Shape | Endpoints |
|---|---|---|
| legacy (REST) | `{"result":"error","errors":[{"code":"RecordNotFoundException","message":"…"}],"meta":{}}` | `items/get`, `users/get_profile`, `items/get_items`, `reviews/history`, `services/master/v1/*` |
| gRPC gateway | `{"code":3,"message":"…","requestId":"…","details":null}` | `v2/entities:search`, `v2/facets:suggest`, `v1/marketplaces/shops/*`, `v2/relateditems/*`, `v2/desiredPriceItems`, `usersocialjp` |

Observed codes

| HTTP | Family | code | Situation |
|---|---|---|---|
| 400 | gRPC | 3 | bad enum value, JSON type mismatch (`cannot unmarshal number into Go value of type string`), unknown `thumbnailTypes` |
| 400 | legacy | `InvalidArgument` | a Shops product id, or a malformed id, passed to `items/get` |
| 400 | legacy | `InvalidRequest` | `items/get_items` with `limit=200` |
| 400 | legacy | `UnsupportedVersionException` | `X-Platform` wrong or absent |
| 401 | gRPC | 16 / 3 | DPoP missing / mismatched |
| 404 | legacy | `RecordNotFoundException`, `UserNotFoundException`, `NotFoundException` | no such item, user or master row |
| 404 | gRPC | 5 | no such Shops product |
| 406 | text (not JSON) | `no accepted candidate variant` | `Accept` mismatch on `master/v2/datasets/*` |
| 404 | text (not JSON) | `404 page not found` | path does not exist |
| 403 | not observed | — | expected when Cloudflare blocks. Fail immediately, never retry |

### 1.4 Rate limiting

Sixty consecutive searches from one IP and key with no pause returned 60/60 200s,
averaging 712 ms. No 429 was observed. Cloudflare sits in front (`CF-RAY`, `__cf_bm`
cookie). The blocking threshold is unknown, so the wrapper defaults to a 0.5 s gap, backs
off exponentially on 429 and 5xx, and treats 403 as a block — failing at once rather than
retrying.

---

## 2. Endpoint index

| # | Method and path | Purpose | Section |
|---|---|---|---|
| 1 | `POST /v2/entities:search` | search and browse | §3 |
| 2 | `POST /v2/facets:suggest` | filter definitions, category tree, brand search | §4 |
| 3 | `GET /items/get` | personal listing detail | §5 |
| 4 | `GET /v1/marketplaces/shops/products/{id}` | Shops product detail | §6 |
| 5 | `GET /users/get_profile` | seller profile | §7.1 |
| 6 | `GET /items/get_items` | a seller's listings | §7.2 |
| 7 | `GET /reviews/history` | reviews | §7.3 |
| 8 | `POST /services/usersocialjp/v1/stats/badges`, `…/has_identity_verified_badge` | badges, identity verification | §7.4 |
| 9 | `POST /v2/relateditems/list-similar-items` | similar items | §8.1 |
| 10 | `GET /search_index/terms` | keyword autocomplete | §8.2 |
| 11 | `GET /v2/desiredPriceItems/{id}/desiredPriceInfo` | desired-price aggregate | §8.3 |
| 12 | `GET /services/master/v1/*`, `GET /master/v2/datasets/*`, `GET /master/get_item_*` | master data | §9 |

Also called by the web item page but not investigated: `POST /v2/products:search`,
`POST /v2/relateditems/component`, `POST /v2/relateditems/query-suggestions` (`limit` must
be 1-6), `services/item_watch/v1/ValidateItem`, `v2/campaigns/component:get`.

---

## 3. Search — `POST /v2/entities:search`

### 3.1 Request body (the captured web-app body, values substituted)

```json
{
  "userId": "",
  "config": {"responseToggles": ["QUERY_SUGGESTION_WEB_1"]},
  "pageSize": 120,
  "pageToken": "",
  "searchSessionId": "<32 hex chars, fixed per session>",
  "source": "BaseSerp",
  "indexRouting": "INDEX_ROUTING_UNSPECIFIED",
  "thumbnailTypes": [],
  "searchCondition": {
    "keyword": "iphone 15 pro",
    "excludeKeyword": "",
    "sort": "SORT_PRICE",
    "order": "ORDER_ASC",
    "status": ["STATUS_ON_SALE"],
    "sizeId": [],
    "categoryId": [],
    "brandId": [],
    "sellerId": [],
    "priceMin": 10000,
    "priceMax": 80000,
    "itemConditionId": [1, 2],
    "shippingPayerId": [2],
    "shippingFromArea": [],
    "shippingMethod": [],
    "colorId": [],
    "hasCoupon": false,
    "attributes": [{"id": "7bd3eacc-ae45-4d73-bc57-a611c9432014", "values": ["340258ac-e220-4722-8c35-7f73b7382831"]}],
    "itemTypes": [],
    "skuIds": [],
    "shopIds": [],
    "excludeShippingMethodIds": []
  },
  "serviceFrom": "suruga",
  "withItemBrand": true,
  "withItemSize": false,
  "withItemPromotions": true,
  "withItemSizes": true,
  "withShopname": false,
  "useDynamicAttribute": true,
  "withSuggestedItems": true,
  "withOfferPricePromotion": true,
  "withProductSuggest": true,
  "withParentProducts": false,
  "withProductArticles": true,
  "withSearchConditionId": false,
  "withAuction": true,
  "laplaceDeviceUuid": "<uuid4, fixed per device>"
}
```

- The web sends `withShopname: false`, but `true` fills in `shopName`. The wrapper
  defaults to `true`.
- `withSearchConditionId: true` adds `searchConditionId` to the response. It is a
  saved-search token and has no use in anonymous scope.
- `thumbnailTypes` is the `mercari.platform.searchadapterjp.v2.ImgType` enum, and **only
  `WEBP` and `JPEG` are accepted**. The value changes the `thumbnails` URL path
  (`/thumb/item/webp/…` versus `/thumb/item/jpeg/…`); an empty array yields webp.
  `IMG_TYPE_*`, `PNG`, `GIF`, `ORIGINAL`, `SMALL`, `LARGE` and `UNSPECIFIED` all give 400.
- Adding a top-level `useNtiersCategory: true` does not change filter results; it only
  matters for `facets:suggest`.
- The echoed `searchCondition` carries undocumented extras: `createdAfterDate`,
  `createdBeforeDate` (unix seconds as strings, default `"0"`) and `promotionValidAt`
  (null). The first two work when sent in a request.

### 3.2 `searchCondition` fields

| Field | Type | Values | Works | Notes |
|---|---|---|---|---|
| `keyword` | str | free text, space-separated AND | yes | an empty string plus filters is a valid browse |
| `excludeKeyword` | str | space-separated | yes | |
| `sort` | enum | `SORT_SCORE` `SORT_CREATED_TIME` `SORT_PRICE` `SORT_NUM_LIKES` | yes | an invalid value gives 400 |
| `order` | enum | `ORDER_DESC` `ORDER_ASC` | yes | ASC only means something for `SORT_PRICE`; it is ignored for created and score |
| `status` | enum[] | `STATUS_ON_SALE` `STATUS_TRADING` `STATUS_SOLD_OUT` | yes | **`[]` means everything** (2,475 on sale versus 6,414 for all). `STATUS_DEFAULT` behaves like everything. The web 「売り切れ」 checkbox is `SOLD_OUT` + `TRADING` |
| `sizeId` | **str[]** | size id (`"2"` = S, `"3"` = M …) | yes | integers give 400. Same result set as the attribute-UUID route (§4) |
| `categoryId` | int[] (str accepted) | ids from both the current and the legacy tree | yes | several ids are OR-ed |
| `brandId` | int[] (str accepted) | brand id (Apple = 3272) | yes | |
| `sellerId` | **str[]** | user id | yes | integers give 400 |
| `priceMin` / `priceMax` | int (str accepted) | 0 = unbounded | yes | |
| `itemConditionId` | int[] | 1-6 | yes | |
| `shippingPayerId` | int[] | 1 buyer, 2 seller | yes | |
| `shippingFromArea` | int[] | prefecture id, **1-47 = JIS X 0401** | yes | all 47 return 200 with non-zero counts and the ranking matches population (Tokyo, Osaka and Fukuoka hit the 15,000 cap; Saga is lowest at 985). No web UI; this is the app's 「発送元の地域」 |
| `shippingMethod` | enum[] | `SHIPPING_METHOD_ANONYMOUS` `SHIPPING_METHOD_JAPAN_POST` `SHIPPING_METHOD_NO_OPTION` | yes | the web 「発送オプション」 |
| `excludeShippingMethodIds` | int[] | shipping-method id (1 = 未定 …) | yes | no web UI |
| `colorId` | int[] | legacy colours 1-12 | partly | it responds, but returns about 4% of what the attribute route finds (11 items for black versus 271). Presumed a stale index. **Do not use** |
| `hasCoupon` | bool | | no effect | |
| `attributes` | `[{id: str, values: str[]}]` | attribute UUID and value UUIDs | yes | values inside one attribute are OR-ed (black 271 → black or white 300); different attributes are AND-ed (black 271 → black and 通常出品 267). The "none of the above" hash works for listing format, discount and appraisal. **Other key spellings such as `valueIds` are silently ignored** |
| `itemTypes` | enum[] | `ITEM_TYPE_MERCARI` `ITEM_TYPE_BEYOND` | yes | the web 「出品者」 (individual / Shops) |
| `skuIds` | str[] | unknown | arbitrary values return 0 | |
| `shopIds` | str[] | Shops storefront id (22 chars) | yes | |
| `createdAfterDate` / `createdBeforeDate` | str or int unix seconds | | yes | Hidden fields. **The server reads both as JST (UTC+9)**: sending `T` actually filters on `created >= T - 32400`. With a one-hour-ago cutoff sent as-is, 17 of 20 results were older than the cutoff; with `+32400` applied, all 3 results were newer. The wrapper sends `ts + 32400` and re-checks `created >= ts` client-side. `createdBeforeDate` behaves the same way: asking for the window `[T-2h, T-1h]` with `+32400` on both bounds returns 60 items all inside it, while leaving the upper bound uncorrected puts it below the lower bound and returns nothing |
| `promotionValidAt` | str | | no effect | |

### 3.3 Response

```json
{
  "meta": {"nextPageToken": "v1:1", "previousPageToken": "", "numFound": "2475", "properties": []},
  "items": [ {} ],
  "components": [
    {"rowNumber": "-1", "querySuggest": {"suggestFacets": {"facets": [ {"facetId": "…", "displayNamesMap": {"ja": "pro"}, "searchableValue": "pro", "searchableKey": "keyword", "leaf": true, "selected": false} ]}}},
    {"rowNumber": "0", "engagementArea": {"empty": {}}}
  ],
  "searchCondition": { },
  "searchConditionId": ""
}
```

An `items[]` element (**every number is a string**)

| Key | Example | Notes |
|---|---|---|
| `id` | `"m77574104522"` / `"2JVoP4vefPkskNLnvGbb9P"` | the latter is a Shops product |
| `sellerId` | `"741769104"` / `"0"` | Shops products report `"0"` |
| `buyerId` | `""` | |
| `status` | `ITEM_STATUS_ON_SALE` `ITEM_STATUS_TRADING` `ITEM_STATUS_SOLD_OUT` | the detail API uses lower case `on_sale` |
| `name`, `title` | | `title` is usually empty |
| `price` | `"81999"` | for an auction this is the current bid |
| `created`, `updated` | `"1788330436"` | unix seconds |
| `thumbnails` | `["https://static.mercdn.net/thumb/item/webp/m…_1.jpg"]` | |
| `photos` | `[{"uri": "https://static.mercdn.net/item/detail/webp/photos/m…_1.jpg"}]` | |
| `itemType` | `ITEM_TYPE_MERCARI` / `ITEM_TYPE_BEYOND` | |
| `itemConditionId` | `"3"` | filled for Shops products too |
| `shippingPayerId` | `"2"` / `"0"` | Shops products report `"0"` |
| `shippingMethodId` | `"14"` / `"0"` | |
| `categoryId` | `"859"` | leaf category |
| `itemBrand` | `{"id": "3272", "name": "Apple", "subName": "Apple"}` or null | camelCase |
| `itemSize` / `itemSizes` | `{"id": "3", "name": "M"}` / a list of the same | |
| `itemPromotions` | `[{"type": "ITEM_PROMOTION_TYPE_DISCOUNT", "details": {"percentage": "30"}}]` | **filled when a time-sale attribute filter is applied** (20 of 20 items with the "10% off or more" filter). Empty with the discount filter or with no filter |
| `shopName`, `shop` | a storefront name, `{"id": "2JSYvWiZ…"}` | Shops only |
| `isNoPrice` | bool | when true, `price` is meaningless. The value 9999999 comes from a mercapi comment and was never observed (assumed) |
| `isLiked` | false | |
| `auction` | `{"id": "", "bidDeadline": "2026-09-02T11:39:00Z", "totalBid": "20", "highestBid": "62000", "initialPrice": "60000"}` or null | camelCase, ISO timestamps |
| `attributes` | `[]` | **always empty in search responses**, even with time-sale or discount filters applied. Item attributes only arrive from the detail API as `item_attributes` |

Shops products (`ITEM_TYPE_BEYOND`) often have `created == updated`, and `created` appears
to move like an update timestamp — the same storefront products keep reappearing at the top
of a created-time sort. That is why the new-listing watcher excludes them by default.

### 3.4 Pagination rules

- `pageToken` is `"v1:<n>"` (zero-based); the first request sends `""`. Assembling the
  token by hand gives the same result as echoing the server's.
- `pageSize` 120 is the standard. 200 and 500 both return at most 131 items.
- `numFound` **is not a total**: it is capped at 15,000; in one run the same query dropped
  to 76 items on page 15, then reported 5,292 from page 19 and continued at 120 items per
  page; in another run `v1:50` onwards returned nothing. **Never compute a page count from
  it.** Stop when `items == []` or `nextPageToken == ""`, keep a safety cap
  (`max_pages`), and de-duplicate by id.
- `numFound` also depends on the sort index. Unfiltered `iphone 15`: 15,000 (capped) for
  score versus 11,178 for created. Priced 10,000-80,000: 2,475 for score, 3,445 for price,
  3,803 for likes.

### 3.5 What the sort options actually do

| `sort` / `order` | Web label | Reality |
|---|---|---|
| `SORT_SCORE` DESC | おすすめ順 | the default |
| `SORT_CREATED_TIME` DESC | 新しい順 | roughly newest-first, but 39 of 120 adjacent pairs were inverted, and old `created` values appear near the top (presumably edits and relists) |
| `SORT_PRICE` ASC / DESC | 価格の安い順 / 高い順 | strict |
| `SORT_NUM_LIKES` DESC | いいね！順 | returns only 71-77 items per page |
| any other combination | not offered | accepted without error and treated as DESC |

---

## 4. Filter definitions — `POST /v2/facets:suggest`

The source of the web sidebar: category tree, brand search, sizes and dynamic attributes.

### 4.1 Request

```json
{
  "facetRequests": [
    {"facetId": "", "withSelectedPaths": true, "withRelevantFacets": true,
     "facetQuery": "apple",
     "config": {"responseToggles": ["DFF_IMPROVEMENT_FACETS_REORDER"]}}
  ],
  "searchSessionId": "<hex32>",
  "searchCondition": { },
  "useNtiersCategory": true,
  "useDynamicAttribute": true
}
```

- `facetId` encoding: `"1" + US + base64(key + US + value)` where `US` is the ASCII unit
  separator `\x1f`. It uses **standard base64 (`+/`, `=` padding kept)**, not the base64url
  of the DPoP token. An empty `value` asks for the top level of that key. Examples:
  `category_id` becomes `"1\x1fY2F0ZWdvcnlfaWQf"`, and `category_id` with `3088` becomes
  `"1\x1fY2F0ZWdvcnlfaWQfMzA4OA=="`.
- `facetId: ""` returns the sidebar section list. **Its size and contents are not
  fixed — see §4.4.**
- `facetQuery` does a partial name search on `brand_id`, matching both romaji and kana and
  returning `nameReading`. Omit the key when not searching; the web sends `""` and both
  return 200.
- `withRelevantFacets: true` adds `relevantFacets`, a set of suggested categories. It was
  only ever populated for a `category_id` facetId **together with a keyword**
  (`iphone 15` gave 9 entries). Root requests and keyword-less category requests return
  none.
- Several `facetRequests` can be sent at once; the web sends one at a time.

### 4.2 Response

```json
{"suggestedFacetMap": {
  "<the requested facetId>": {
    "suggestFacets": {"facets": [ ], "nextPageToken": ""},
    "selectedPaths": {},
    "relevantFacets": {"facets": [ ]}
}}}
```

A facet entry

| Key | Meaning |
|---|---|
| `facetId` | pass it straight back to fetch the children |
| `displayNamesMap` | `{"ja": "...", "en": "..."}` |
| `searchableKey` | empty in the top-level list; otherwise the search field key (`category_id`, `keyword` …) |
| `searchableValue` | the value to put in the search condition. For a top-level section it is the field key or the attribute UUID |
| `leaf` | false means there are children |
| `selected`, `selectedState` | reflects the condition that was sent |
| `metadata` | brands carry `nameReading`, colours carry `colorHex`, otherwise null. **No item count is provided** |
| `parentPath`, `nestedFacets` | null in everything observed |

### 4.3 Mapping `searchableValue` onto `searchCondition`

| Section `searchableValue` | Search field | Conversion |
|---|---|---|
| `category_id` | `categoryId` | int |
| `brand_id` | `brandId` | int |
| `status` | `status` | `on_sale` becomes `STATUS_ON_SALE`; `sold_out,trading` becomes both enums |
| `item_types` | `itemTypes` | `mercari` becomes `ITEM_TYPE_MERCARI`; `beyond` becomes `ITEM_TYPE_BEYOND` |
| `item_condition_id` | `itemConditionId` | int |
| `shipping_payer_id` | `shippingPayerId` | int |
| `shipping_method_id` | `shippingMethod` | `anonymous` becomes `SHIPPING_METHOD_ANONYMOUS`, and so on |
| `price` | `priceMin` / `priceMax` | |
| `exclude_keyword` | `excludeKeyword` | |
| `size_id` (legacy key, groups `g1`…) | `sizeId` | the leaf value as a string |
| `color_id` (legacy key) | `colorId` | int |
| a UUID (colour, size, discount, appraisal, listing format, refurbished, time sale) | `attributes[{id: section UUID, values: [leaf UUID]}]` | as-is |

The "none of the above" options (通常商品, 通常出品, 利用不可) all share the hash
`B38F1DC9286E0B80812D9B19DB14298C1FF1116CA8332D9EE9061026635C9088`.

### 4.4 The section list changes (observed 2026-09-02)

Within about twenty minutes on the same day, the `facetId: ""` response was seen in two
variants.

| Variant | Sections | サイズ | 色 | 出品者 (`item_types`) |
|---|---|---|---|---|
| A (dynamic attributes) | 16 | `f42ae390-…` (UUID) | `7bd3eacc-…` (UUID) | present |
| B (legacy keys) | 15 | `size_id` | `color_id` | **absent** |

- Request parameters are not the cause. Toggling `withSelectedPaths`,
  `withRelevantFacets`, `useDynamicAttribute`, `useNtiersCategory` and the presence of a
  keyword all returned the same variant at the same moment. Presumably an A/B test or a
  staged rollout.
- **The search fields keep working in both variants.** While variant B was being served,
  `itemTypes` still filtered correctly (`iphone 15`, 10,000-80,000: 2,469 unfiltered, 1,165
  for MERCARI, 1,305 for BEYOND), and requesting the colour and size attribute UUIDs
  directly as a `facetId` returned their value lists as usual (16 colours, 13 size groups).
- The wrapper therefore **does not depend on the section list**: attribute values are
  fetched by section UUID (a code constant), and the section list is used for diagnostics
  only. The health check requires just the stably observed sections — `category_id`,
  `brand_id`, `status`, `item_condition_id`, `price` — and reports any other difference as
  a warning.

### 4.5 Attribute display names change too (observed 2026-09-02)

The value list for listing format (`d664efe3-…`) shrank from three entries to two, and one
was renamed.

| Earlier snapshot | Current | Value UUID | Result count (`iphone 15`, 10,000-80,000) |
|---|---|---|---|
| 通常オークション | **オークション** | `3b6eac8c-7be5-4c9c-b537-7c05cd3c4905` | 38 |
| 3時間オークション | gone from the list | `dd317554-b1ba-40a1-b9b5-475238c0765e` | 1 — **the UUID still filters** |
| 通常出品 | 通常出品 | `B38F1DC9…9088` | the "none of the above" hash |

The appraisal value was likewise seen as `あんしん鑑定利用可能` rather than `利用可能`.
Name-based resolution is **exact match** (03 §3.5), so a rename breaks it. The wrapper
tries the live lookup first and only falls back to the bundled snapshot, warning when it
does. A value that has disappeared from the list still filters if its UUID is passed
directly through `SearchQuery.attributes(AttributeFilter(...))`.

### 4.6 The web sidebar and the API disagree (browser check, 2026-09-02)

Recorded in `tests/fixtures/web_baseline.json`. At the same moment:

- Web sidebar: 16 sections including 出品者, listing-format options
  `すべて / オークション / 通常出品`, and 16 colours.
- API `facets:suggest`: 15 sections with no 出品者, and size and colour as the legacy keys
  `size_id` and `color_id`.

So the variants in §4.4 include the case where the web and the API are served different
definitions. **The attribute values themselves agree**: the 16 colour names and their order
match, and the listing-format rename is reflected on the web too.

Also confirmed about the web search page:

- There is **no result-count label**. Counting results means counting `item-cell` elements
  in the grid.
- Attribute parameters in the URL (`<attribute UUID>=<value UUID>`) are reflected in the
  sidebar checkboxes and the chips at the top, but **not in the first paint**, which shows
  the unfiltered page of 120. A second request applies them.
- For the full filter stack (`iphone 15`, 10,000-80,000, conditions 1 and 2, seller pays
  shipping, colour ブラック系, 通常出品) the web showed **35 items**, and `approx_total`
  from this package was also **35**.

---

## 5. Personal listing detail — `GET /items/get`

Query, verbatim from the web item page:
`id=<m…>&include_item_attributes=true&include_product_page_component=true&include_non_ui_item_attributes=true&include_donation=true&include_item_attributes_sections=true&include_auction=true`

Extra option: `country_code=US` adds
`converted_price: {"price": 452.64, "currency_code": "USD", "rate_updated": …}`.
`include_offer_like_coupon_display` and `include_offer_coupon_display` are harmless but the
web does not send them.

The response is `{"result": "OK", "data": {…}, "meta": {}}`, and `data` has 50 keys
(snake_case, with real numeric types):

`id, seller{id,name,photo_url,photo_thumbnail_url,created,num_sell_items,ratings{good,normal,bad},num_ratings,score,is_official,quick_shipper,is_followable,is_blocked,star_rating_score,register_sms_confirmation,is_inactive,region_code,register_sms_confirmation_at}, buyer{id,name} (while trading or sold), status("on_sale"|"trading"|"sold_out"|"stop"|"cancel"), name, price, description, photos[], photo_paths[], thumbnails[], item_category{id,name,display_order,parent_category_id,parent_category_name,root_category_id,root_category_name}, item_category_ntiers{the current tree}, parent_categories_ntiers[{id,name,display_order}], item_brand{id,name,sub_name} (absent when none), item_condition{id,name}, colors[{id,name,rgb}], shipping_payer{id,name,code}, shipping_method{id,name,is_deprecated}, shipping_from_area{id,name}, shipping_duration{id,name,min_days,max_days}, shipping_class{id,fee}, delivery_facility_type, num_likes, num_comments, comments[{id,message,user{id,name,photo_url,photo_thumbnail_url},created}], registered_prices_count, created, updated, pager_id, liked, checksum, is_dynamic_shipping_fee, application_attributes{}, is_shop_item("yes"|"no"), hash_tags[], is_anonymous_shipping, is_web_visible, is_offerable, is_offerable_v2, is_organizational_user, organizational_user_status, is_stock_item, is_cancelable, shipped_by_worker, additional_services[], has_additional_service, has_like_list, is_degraded, is_dismissed, meta_title, meta_subtitle, photo_descriptions[], transaction_evidence{id,status} (once sold), item_attributes[{id,text,values[{id,text}],deep_facet_filterable,show_on_ui}], auction_info{id,start_time,expected_end_time,bid_deadline_duration_seconds,bid_total_duration_seconds,total_bids,initial_price,highest_bid,state("STATE_ONGOING"|"STATE_NO_BID"…),auction_type("AUCTION_TYPE_NORMAL"…)}`

- The value id of the `item_attributes` entry whose `text` is `色` is the same UUID the
  search `attributes` filter takes, so a filter can be reconstructed from a listing. That
  entry, however, has `show_on_ui: false` and `deep_facet_filterable: true` — **the set of
  attributes shown in the UI is not the set that can be filtered on**. Use
  `deep_facet_filterable` to decide (colour `7bd3eacc-…` with value `27678b0c-…`).
- Listings that are not auctions **have no `auction_info` key at all**.
- `item_attributes` also contains non-UI rows such as `photo_description`, whose values are
  empty strings.
- Numbers here are **real numbers** (`price: 70000`) and `status` is lower case
  (`on_sale`) — the exact opposite of the search response, so the model parsers absorb both
  spellings.
- Errors: 404 `RecordNotFoundException` for an unknown id; 400 `InvalidArgument` for a
  malformed id or a Shops product id. marvinody's notes mention 403 for expired listings,
  which was not reproduced.

## 6. Shops product detail — `GET /v1/marketplaces/shops/products/{productId}?view=FULL`

The full key set was dumped on 2026-09-02. Fixture: `tests/fixtures/shops_product.json`.

Top level, 10 keys: `name` (the product id, 22 chars), `displayName`, `price` (str),
`thumbnail`, `createTime` and `updateTime` (ISO 8601 with `Z`), `productTags` (a list —
`sold_out` once sold, empty while on sale), `attributes` (empty in everything observed),
`isBlockedShop` (bool) and `productDetail`.

`productDetail` (camelCase, numbers mixed between str and int)

| Key | Content |
|---|---|
| `shop` | `{name (the storefront id), displayName, thumbnail, shopStats{shopId, score(int), reviewCount(str)}, allowDirectMessage, shopItems[], isInboundXb, badges[], hasApprovedBrandScreening, alwaysShowStock, isOwner, enableMultiplePurchase}` |
| `photos` | list |
| `description` | str |
| `categories` | `[{categoryId(str), displayName, parentId(str), rootId(str), hasChild(bool)}]`, ordered leaf to root. The counterpart of `item_category_ntiers` for personal listings |
| `brand` | null or a brand object (null in everything observed) |
| `condition` | `{displayName, description}` — **no numeric id**, unlike `item_condition{id,name}` for personal listings |
| `shippingMethod` | `{shippingMethodId(str), displayName, isAnonymous(bool)}` |
| `shippingPayer` | `{shippingPayerId(str), displayName, code}` |
| `shippingDuration` | `{shippingDurationId(str), displayName, minDays, maxDays}` |
| `shippingFromArea` | `{shippingAreaCode(str), displayName}` |
| `promotions` | list |
| `productStats` | `{productId, score(int), reviewCount(int), likesCount(int)}` |
| `variants` | `[{variantId, displayName, quantity(str), size(str), attributes[], maxQuantityPerOrder(int)}]` — a concept personal listings do not have |
| `timeSaleDetails`, `shippingFeeConfig`, `variationGrouping`, `buyerPromotion`, `followPromotion`, `lastPurchasedDateTime`, `realCardReward`, `mercardCampaign`, `seoMetadata`, `productPreOrder`, `shippingFeeCalculationConfiguration` | all null in everything observed |

- Sale state comes from `productTags` (`"sold_out" in productTags`). There is no status
  field.
- An unknown id gives 404 with gRPC code 5.
- No field name or type overlaps with `items/get`, so the wrapper keeps two models and
  `get_detail()` routes before sending (§5, 03 §1.4).

## 7. Seller

### 7.1 `GET /users/get_profile?user_id=<id>&_user_format=profile`

Without `_user_format=profile`, `created` and `num_sell_items` come back as 0 — confirmed
directly: 0 and 0 without the parameter, 1601972891 and 24 with it.

Keys of `data`: `id, name, photo_url, photo_thumbnail_url, introduction, created,
num_sell_items, ratings{good,normal,bad}, polarized_ratings, num_ratings, score,
star_rating_score, follower_count, following_count, is_official, is_organizational_user,
organizational_user_status, is_followable, is_blocked, is_following, is_following_requester,
hide_profile, register_sms_confirmation, kyc_type, is_verified_proxy, proper`.

The response also carries twelve fields that **must not be modelled**: `email`,
`phone_number`, `current_point`, `current_sales`, `num_ticket`, `iv_code`,
`bounce_mail_flag`, `has_detach_phone_number`, `pp_edit_url`, `pp_show_url`,
`tokushouhou_edit_url`, `tokushouhou_show_url`. An unknown user gives 404
`UserNotFoundException`.

### 7.2 `GET /items/get_items`

Query: `seller_id` (required), `limit` (the web sends 51; up to 100 confirmed, 200 gives
400 `InvalidRequest`), `status=on_sale,trading,sold_out` (CSV), `with_auction=true`,
`exclude_archived_item=true` (optional) and `max_pager_id=<n>` for paging.

Response: `{"result":"OK","data":[…],"meta":{"has_next": bool}}`. Keys of `data[]`: `id,
name, price, status, thumbnails, created, updated, pager_id, is_no_price, is_archived,
is_url_limited, item_brand, item_category, item_category_ntiers, parent_categories_ntiers,
root_category_id, shipping_from_area, shipping_method_id, num_likes, num_comments, item_pv,
recent_item_pv, liked, seller, auction_info` (the last only for auctions).

Paging: while `has_next` is true, re-request with the last `pager_id - 1` as
`max_pager_id`. No overlap was observed between pages.

### 7.3 `GET /reviews/history`

Query: `user_id`, `subject=seller,buyer`, `fame=good,normal,bad`, `limit` (up to 100
confirmed) and `max_pager_id`. Paging works exactly as for `get_items`, again with no
overlap. Response `data[]`: `subject, fame, message, user{id,name,photo_url}, created,
pager_id`. Response `meta`: `score, ratings{}, num_ratings, star_rating_score, has_next,
requested`.

### 7.4 Badges — `POST /services/usersocialjp/v1/stats/badges` and `…/has_identity_verified_badge`

Body `{"userId": "<id>"}`. Responses `{"badges": [{id,name,description,iconUrl}]}` and
`{"hasBadge": true}`. An empty `badges` array is normal.

## 8. Around an item

### 8.1 `POST /v2/relateditems/list-similar-items`

Body `{"itemId": "<id>", "pageSize": 15, "itemTypesFlag": "ITEM_TYPES_MERCARI_AND_SHOPS",
"includeAds": false, "pageToken": ""}`. Response `{"items": […], "ads": [],
"nextPageToken": ""}`, where each item has ten keys: `id, name, price(str),
status(lower case), thumbnail, type, auctionInfo{id, highestBid}, isLiked, categoryId(str),
shippingMethodId(str)`.

`auctionInfo` is present even for listings that are not auctions, with `id: "0"` and
`highestBid` equal to the current price — **it cannot be used to detect auctions**.

### 8.2 `GET /search_index/terms?word=<q>&brand_category_result_included=true`

Response `{"data": [{"MixedQuery": {"Query": {"title", "subtitle", "search_params":
{"keyword", "item_categories": [{id, name}]}, "score"}}}]}`.

### 8.3 `GET /v2/desiredPriceItems/{itemId}/desiredPriceInfo`

Response `{"name": "desiredPriceItems/m…", "registeredCount", "highestDesiredPrice",
"lowestDesiredPrice", "highestDesiredPriceCount", "userRegisteredDesiredPrice"}` — all
strings.

## 9. Master data

| Path | Header | Response | Notes |
|---|---|---|---|
| `GET /master/v2/datasets/item_categories` | **`Accept: application/json`** | `{"itemCategories": [{id, name, level, parentCategoryId, parentCategoryName, rootCategoryId, rootCategoryName, displayOrder, hasChild, showItemBrands, shortLabel, imageUrls{}}]}`, 8,784 rows | **the current tree, the same one the web uses**; 22 roots |
| `GET /master/v2/datasets/item_category_groups` | same | `{"itemCategoryGroups": [{id, name, itemCategoryIds[]}]}` | |
| `GET /master/v2/datasets/item_brands` | same | `{"itemBrands": [{id, name, subname, initial, jaPronunciation, nameJaFurigana}]}`, **52,589 rows** | two kana readings, which the v1 dataset lacks |
| `GET /master/v2/datasets/shipping_methods` | same | `{"shippingMethods": [{id, name, displayOrder, shippingPayerId, isAnonymous, isDeprecated, created, updated}]}`, **21 rows** | `isDeprecated` and `isAnonymous` are the strings `"yes"` and `"no"`. This is where the ids for `excludeShippingMethodIds` come from |
| `GET /services/master/v1/itemConditions` | none | `{"conditions": [{id, name, subname}], "nextPageToken"}`, 6 rows | |
| `GET /services/master/v1/itemSizes` | | `{"sizes": [{id, name, groupId, group}]}` | size id to group mapping |
| `GET /services/master/v1/itemColors` | | `{"colors": [{id, name, rgb}]}`, 12 colours | legacy |
| `GET /services/master/v1/shippingPayers` | | `{"payers": [{id, name, code}]}` | |
| `GET /services/master/v1/shippingMethods` | | `{"methods": [{id, name, payerId, type, isDeprecated}]}` | |
| `GET /services/master/v1/itemCategories` | | `{"categories": [{id, name, level, parentId, itemBrandGroupId, itemSizeGroupId}]}` | **the legacy tree** |
| `GET /services/master/v1/itemBrands` | | `{"brands": [{id, name, subname, initial, groupId[]}]}` | large |
| `GET /master/get_item_categories`, `/master/get_item_brands` | | `{"result":"OK","data":[a nested tree]}` | legacy, old tree. Not used |

No prefecture master endpoint was found (`services/master/v1/prefectures` and
`master/get_prefectures` both 404). `shippingFromArea` works for all of 1-47 and the count
distribution matches the JIS X 0401 ordering, so the wrapper uses JIS codes directly.

## 10. Unresolved

- Whether the web 「すべて」 status checkbox sends `status: []` in the request body. The URL
  behaviour is confirmed (the parameter is `status=on_sale` when 「販売中のみ表示」 is on and
  absent for 「すべて」), but the body could not be captured. The API-side meaning of
  `status: []` (everything) is confirmed.
- Whether app-only filters exist beyond `shippingFromArea`. No device was available to
  capture app traffic.
- `skuIds` semantics; `isNoPrice` with the 9999999 sentinel; the exact 429 body.
