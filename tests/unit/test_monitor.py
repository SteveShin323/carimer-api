"""Phase 5: the new-listing watcher, driven by a fake clock and a fake client."""

from __future__ import annotations

import json
from typing import Any

import httpx
import respx

from carimer import Client, TransportOptions
from carimer.api.search import SEARCH_URL
from carimer.models.enums import ItemType, Order, Sort
from carimer.models.search import SearchItem, SearchPage
from carimer.search.monitor import OVERLAP_SECONDS, watch_new_listings
from carimer.search.query import JST_OFFSET_SECONDS, SearchQuery

T0 = 1_788_000_000


def _item(item_id: str, created: int, *, shops: bool = False) -> dict[str, Any]:
    return {
        "id": item_id,
        "name": item_id,
        "price": "1000",
        "created": str(created),
        "updated": str(created),
        "itemType": "ITEM_TYPE_BEYOND" if shops else "ITEM_TYPE_MERCARI",
    }


class FakeClient:
    """Replays canned pages and records the condition of every request."""

    def __init__(self, pages: list[list[dict[str, Any]]]) -> None:
        self._pages = pages
        self.conditions: list[dict[str, Any]] = []

    def search(self, query: SearchQuery | str, *, page_token: str = "", page_size: int = 120) -> SearchPage:
        assert not isinstance(query, str)
        self.conditions.append(query.to_condition())
        index = len(self.conditions) - 1
        items = self._pages[index] if index < len(self._pages) else []
        return SearchPage.from_api({"meta": {"numFound": str(len(items))}, "items": items})


class Clock:
    def __init__(self, start: float = T0) -> None:
        self.now = start
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_first_cycle_seeds_without_calling_back() -> None:
    client = FakeClient([[_item("m1", T0 - 10), _item("m2", T0 - 20)]])
    clock = Clock()
    calls: list[list[SearchItem]] = []
    since = watch_new_listings(
        client,
        "ポケモンカード",
        on_new=calls.append,
        interval=30,
        max_cycles=1,
        now=clock,
        sleep=clock.sleep,
    )
    assert calls == []
    assert since == T0 - 10  # newest created seen
    assert "createdAfterDate" not in client.conditions[0]
    assert client.conditions[0]["sort"] == Sort.CREATED_TIME.value
    assert client.conditions[0]["order"] == Order.DESC.value


def test_later_cycles_report_only_new_ids() -> None:
    client = FakeClient(
        [
            [_item("m1", T0 - 10)],  # seed
            [_item("m1", T0 - 10), _item("m2", T0 + 5)],  # m1 repeats, m2 is new
            [_item("m2", T0 + 5), _item("m3", T0 + 40)],  # m2 repeats, m3 is new
        ]
    )
    clock = Clock()
    batches: list[list[str]] = []
    since = watch_new_listings(
        client,
        SearchQuery("ポケモンカード"),
        on_new=lambda items: batches.append([i.id for i in items]),
        interval=30,
        max_cycles=3,
        now=clock,
        sleep=clock.sleep,
    )
    assert batches == [["m2"], ["m3"]]
    assert since == T0 + 40
    assert clock.slept == [30, 30]


def test_request_uses_the_jst_corrected_overlapping_window() -> None:
    client = FakeClient([[_item("m1", T0)], []])
    clock = Clock()
    watch_new_listings(
        client,
        "x",
        on_new=lambda items: None,
        interval=10,
        max_cycles=2,
        now=clock,
        sleep=clock.sleep,
    )
    expected = str(T0 - OVERLAP_SECONDS + JST_OFFSET_SECONDS)
    assert client.conditions[1]["createdAfterDate"] == expected


def test_items_older_than_since_are_dropped_even_if_the_server_returns_them() -> None:
    """The client-side re-check is what makes a server date-handling change harmless."""
    client = FakeClient(
        [
            [_item("m1", T0)],
            [_item("old", T0 - 3600), _item("older", T0 - 7200), _item("new", T0 + 1)],
        ]
    )
    clock = Clock()
    batches: list[list[str]] = []
    watch_new_listings(
        client,
        "x",
        on_new=lambda items: batches.append([i.id for i in items]),
        interval=5,
        max_cycles=2,
        now=clock,
        sleep=clock.sleep,
    )
    assert batches == [["new"]]


def test_callback_items_are_newest_first() -> None:
    client = FakeClient([[_item("m0", T0)], [_item("a", T0 + 10), _item("c", T0 + 30), _item("b", T0 + 20)]])
    clock = Clock()
    batches: list[list[str]] = []
    watch_new_listings(
        client,
        "x",
        on_new=lambda items: batches.append([i.id for i in items]),
        interval=5,
        max_cycles=2,
        now=clock,
        sleep=clock.sleep,
    )
    assert batches == [["c", "b", "a"]]


def test_explicit_since_reports_from_the_first_cycle() -> None:
    client = FakeClient([[_item("m1", T0 + 5)]])
    clock = Clock()
    batches: list[list[str]] = []
    watch_new_listings(
        client,
        "x",
        on_new=lambda items: batches.append([i.id for i in items]),
        since=T0,
        interval=5,
        max_cycles=1,
        now=clock,
        sleep=clock.sleep,
    )
    assert batches == [["m1"]]


def test_shops_items_are_excluded_by_default() -> None:
    client = FakeClient([[_item("m1", T0)], [_item("shop1", T0 + 5, shops=True)]])
    clock = Clock()
    watch_new_listings(
        client,
        "x",
        on_new=lambda items: None,
        interval=5,
        max_cycles=1,
        now=clock,
        sleep=clock.sleep,
    )
    assert client.conditions[0]["itemTypes"] == [ItemType.MERCARI.value]


def test_include_shops_leaves_item_types_empty() -> None:
    client = FakeClient([[_item("m1", T0)]])
    clock = Clock()
    watch_new_listings(
        client,
        "x",
        on_new=lambda items: None,
        include_shops=True,
        max_cycles=1,
        now=clock,
        sleep=clock.sleep,
    )
    assert client.conditions[0]["itemTypes"] == []


def test_explicit_item_types_are_respected() -> None:
    client = FakeClient([[_item("m1", T0)]])
    clock = Clock()
    watch_new_listings(
        client,
        SearchQuery("x").item_types(ItemType.BEYOND),
        on_new=lambda items: None,
        max_cycles=1,
        now=clock,
        sleep=clock.sleep,
    )
    assert client.conditions[0]["itemTypes"] == [ItemType.BEYOND.value]


def test_no_sleep_after_the_final_cycle() -> None:
    client = FakeClient([[_item("m1", T0)]])
    clock = Clock()
    watch_new_listings(
        client,
        "x",
        on_new=lambda items: None,
        interval=99,
        max_cycles=1,
        now=clock,
        sleep=clock.sleep,
    )
    assert clock.slept == []


def test_empty_seed_page_falls_back_to_the_clock() -> None:
    client = FakeClient([[]])
    clock = Clock()
    since = watch_new_listings(
        client, "x", on_new=lambda items: None, max_cycles=1, now=clock, sleep=clock.sleep
    )
    assert since == int(T0)


def test_client_facade_watch_sends_the_expected_body() -> None:
    responses = [
        httpx.Response(200, json={"meta": {"numFound": "1"}, "items": [_item("m1", T0)]}),
        httpx.Response(200, json={"meta": {"numFound": "0"}, "items": []}),
    ]
    with respx.mock as mock:
        route = mock.post(SEARCH_URL).mock(side_effect=responses)
        with Client(options=TransportOptions(min_interval=0)) as client:
            client.watch_new_listings("x", on_new=lambda items: None, interval=0, max_cycles=2)
    second = json.loads(route.calls[1].request.content)["searchCondition"]
    assert second["createdAfterDate"] == str(T0 - OVERLAP_SECONDS + JST_OFFSET_SECONDS)
    assert second["itemTypes"] == [ItemType.MERCARI.value]


class PagedFakeClient:
    def __init__(self, pages: list[tuple[list[dict[str, Any]], str]]) -> None:
        self._pages = pages
        self.tokens: list[str] = []
        self.conditions: list[dict[str, Any]] = []

    def search(self, query: SearchQuery | str, *, page_token: str = "", page_size: int = 120) -> SearchPage:
        assert not isinstance(query, str)
        self.tokens.append(page_token)
        self.conditions.append(query.to_condition())
        items, next_token = self._pages[len(self.tokens) - 1]
        return SearchPage.from_api(
            {"meta": {"numFound": str(len(items)), "nextPageToken": next_token}, "items": items}
        )


def test_each_poll_cycle_exhausts_the_created_time_window() -> None:
    client = PagedFakeClient(
        [
            ([_item("newest", T0 + 30), _item("duplicate", T0 + 20)], "page-2"),
            ([_item("duplicate", T0 + 20), _item("deep", T0 + 10)], ""),
        ]
    )
    batches: list[list[str]] = []

    since = watch_new_listings(
        client,
        "x",
        on_new=lambda items: batches.append([item.id for item in items]),
        since=T0,
        max_cycles=1,
        sleep=lambda _: None,
    )

    assert client.tokens == ["", "page-2"]
    assert batches == [["newest", "duplicate", "deep"]]
    assert since == T0 + 30


def test_page_cap_warns_and_does_not_advance_the_watermark(caplog: Any) -> None:
    client = PagedFakeClient([([_item("new", T0 + 30)], "page-2")])

    since = watch_new_listings(
        client,
        "x",
        on_new=lambda items: None,
        since=T0,
        max_cycles=1,
        max_pages_per_cycle=1,
        sleep=lambda _: None,
    )

    assert since == T0
    assert any("listings beyond the cap may be missed" in record.message for record in caplog.records)


def test_seen_ids_are_pruned_after_the_overlap_window() -> None:
    client = FakeClient(
        [
            [_item("moving", T0 + 1)],
            [_item("later", T0 + 100)],
            [_item("moving", T0 + 110)],
        ]
    )
    batches: list[list[str]] = []

    watch_new_listings(
        client,
        "x",
        on_new=lambda items: batches.append([item.id for item in items]),
        since=T0,
        include_shops=True,
        interval=0,
        max_cycles=3,
        sleep=lambda _: None,
    )

    assert batches == [["moving"], ["later"], ["moving"]]


async def test_async_watcher_awaits_a_coroutine_callback() -> None:
    class FakeAsyncClient(FakeClient):
        async def search(  # type: ignore[override]
            self, query: SearchQuery | str, *, page_token: str = "", page_size: int = 120
        ) -> SearchPage:
            return FakeClient.search(self, query, page_token=page_token, page_size=page_size)

    from carimer.search.monitor import awatch_new_listings

    client = FakeAsyncClient([[_item("m1", T0)], [_item("m2", T0 + 5)]])
    batches: list[list[str]] = []

    async def on_new(items: list[SearchItem]) -> None:
        batches.append([item.id for item in items])

    since = await awatch_new_listings(
        client, "x", on_new=on_new, interval=0, max_cycles=2, now=lambda: float(T0)
    )
    assert batches == [["m2"]]
    assert since == T0 + 5


async def test_async_watcher_exhausts_the_created_time_window() -> None:
    class PagedAsyncClient(PagedFakeClient):
        async def search(  # type: ignore[override]
            self, query: SearchQuery | str, *, page_token: str = "", page_size: int = 120
        ) -> SearchPage:
            return PagedFakeClient.search(self, query, page_token=page_token, page_size=page_size)

    from carimer.search.monitor import awatch_new_listings

    client = PagedAsyncClient(
        [
            ([_item("newest", T0 + 30)], "page-2"),
            ([_item("deep", T0 + 10)], ""),
        ]
    )
    batches: list[list[str]] = []

    since = await awatch_new_listings(
        client,
        "x",
        on_new=lambda items: batches.append([item.id for item in items]),
        since=T0,
        max_cycles=1,
    )

    assert client.tokens == ["", "page-2"]
    assert batches == [["newest", "deep"]]
    assert since == T0 + 30
