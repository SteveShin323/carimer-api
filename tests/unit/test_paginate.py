"""Phase 2: pagination stops on empty items, empty token or ``max_pages`` (01 §3.4)."""

from __future__ import annotations

from typing import Any

from carimer.models.search import SearchPage
from carimer.search import paginate
from carimer.search.query import SearchQuery


def _page(items: list[str], next_token: str, num_found: str = "5000") -> dict[str, Any]:
    return {
        "meta": {"nextPageToken": next_token, "previousPageToken": "", "numFound": num_found},
        "items": [
            {"id": item_id, "name": item_id, "price": "100", "itemType": "ITEM_TYPE_MERCARI"}
            for item_id in items
        ],
    }


class FakeClient:
    """Replays canned pages and records the tokens it was asked for."""

    def __init__(self, pages: list[dict[str, Any]]) -> None:
        self._pages = pages
        self.tokens: list[str] = []

    def search(self, query: SearchQuery | str, *, page_token: str = "", page_size: int = 120) -> SearchPage:
        self.tokens.append(page_token)
        index = len(self.tokens) - 1
        payload = self._pages[index] if index < len(self._pages) else _page([], "")
        return SearchPage.from_api(payload)


def test_walks_pages_until_the_token_runs_out() -> None:
    client = FakeClient([_page(["m1", "m2"], "v1:1"), _page(["m3"], "")])
    pages = list(paginate.iter_pages(client, "x"))
    assert [len(page.items) for page in pages] == [2, 1]
    assert client.tokens == ["", "v1:1"]
    assert all(page.truncated is False for page in pages)


def test_stops_on_an_empty_page_without_yielding_it() -> None:
    client = FakeClient([_page(["m1"], "v1:1"), _page([], "v1:2")])
    pages = list(paginate.iter_pages(client, "x"))
    assert len(pages) == 1
    assert client.tokens == ["", "v1:1"]


def test_first_page_is_yielded_even_when_empty() -> None:
    """So that a zero-result query still exposes ``approx_total``."""
    client = FakeClient([_page([], "", num_found="0")])
    pages = list(paginate.iter_pages(client, "x"))
    assert len(pages) == 1
    assert pages[0].approx_total == 0


def test_max_pages_stops_the_walk_and_flags_truncation() -> None:
    pages_data = [_page([f"m{i}"], f"v1:{i + 1}") for i in range(5)]
    client = FakeClient(pages_data)
    pages = list(paginate.iter_pages(client, "x", max_pages=3))
    assert len(pages) == 3
    assert pages[-1].truncated is True
    assert [p.truncated for p in pages[:-1]] == [False, False]


def test_last_page_is_not_flagged_truncated_when_results_ran_out() -> None:
    client = FakeClient([_page(["m1"], "v1:1"), _page(["m2"], "")])
    pages = list(paginate.iter_pages(client, "x", max_pages=2))
    assert pages[-1].truncated is False


def test_iter_items_deduplicates_repeated_ids() -> None:
    """Deep pages repeat results, so ids are de-duplicated (01 §3.4)."""
    client = FakeClient([_page(["m1", "m2"], "v1:1"), _page(["m2", "m3"], "")])
    ids = [item.id for item in paginate.iter_items(client, "x")]
    assert ids == ["m1", "m2", "m3"]


def test_iter_items_honours_max_items() -> None:
    client = FakeClient([_page(["m1", "m2", "m3"], "v1:1")])
    ids = [item.id for item in paginate.iter_items(client, "x", max_items=2)]
    assert ids == ["m1", "m2"]
    assert client.tokens == [""]  # stopped before fetching another page


def test_page_size_is_passed_through() -> None:
    seen: list[int] = []

    class SizeRecordingClient(FakeClient):
        def search(
            self, query: SearchQuery | str, *, page_token: str = "", page_size: int = 120
        ) -> SearchPage:
            seen.append(page_size)
            return super().search(query, page_token=page_token, page_size=page_size)

    client = SizeRecordingClient([_page(["m1"], "")])
    list(paginate.iter_pages(client, "x", page_size=30))
    assert seen == [30]


class FakeAsyncClient(FakeClient):
    async def search(  # type: ignore[override]
        self, query: SearchQuery | str, *, page_token: str = "", page_size: int = 120
    ) -> SearchPage:
        return FakeClient.search(self, query, page_token=page_token, page_size=page_size)


async def test_async_iterators_behave_the_same() -> None:
    client = FakeAsyncClient([_page(["m1", "m2"], "v1:1"), _page(["m2", "m3"], "")])
    pages = [page async for page in paginate.aiter_pages(client, "x")]
    assert [len(p.items) for p in pages] == [2, 2]

    client = FakeAsyncClient([_page(["m1", "m2"], "v1:1"), _page(["m2", "m3"], "")])
    ids = [item.id async for item in paginate.aiter_items(client, "x")]
    assert ids == ["m1", "m2", "m3"]


async def test_async_max_pages_flags_truncation() -> None:
    client = FakeAsyncClient([_page([f"m{i}"], f"v1:{i + 1}") for i in range(4)])
    pages = [page async for page in paginate.aiter_pages(client, "x", max_pages=2)]
    assert len(pages) == 2
    assert pages[-1].truncated is True


def test_truncated_describes_the_walk_not_the_page() -> None:
    """``max_pages=1`` flags the first page; a bare ``search()`` of the same page does not.

    ``truncated`` answers "did the iterator stop early?", so the two entry points
    legitimately disagree. ``has_next`` is the per-page question.
    """
    payload = _page(["m1"], "v1:1")

    client = FakeClient([payload])
    (only_page,) = list(paginate.iter_pages(client, "x", max_pages=1))
    assert only_page.truncated is True
    assert only_page.has_next is True

    direct = SearchPage.from_api(payload)
    assert direct.truncated is False
    assert direct.has_next is True


def test_truncated_is_false_when_the_page_is_the_last_one() -> None:
    client = FakeClient([_page(["m1"], "")])
    (only_page,) = list(paginate.iter_pages(client, "x", max_pages=1))
    assert only_page.truncated is False
    assert only_page.has_next is False
