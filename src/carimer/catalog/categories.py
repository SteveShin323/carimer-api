"""The current (ntiers) category tree, 8,784 nodes (01 §9, 02 §2).

Loaded from ``master/v2/datasets/item_categories`` — the *new* tree with 22 roots, the
same one the web app shows. The legacy ``master/get_item_categories`` (13 roots) is
deliberately unused: ids overlap between the two trees but mean different things, so
mixing them mislabels results.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from carimer.api import master as master_api
from carimer.catalog.facets_client import nodes_from_dataset
from carimer.models.facets import CategoryNode

if TYPE_CHECKING:
    from carimer.transport.base import Request

__all__ = ["AsyncCategories", "Categories", "CategoryTree"]

DATASET = "item_categories"


class _Sender(Protocol):
    def send(self, request: Request) -> dict[str, Any]: ...


class _AsyncSender(Protocol):
    async def send(self, request: Request) -> dict[str, Any]: ...


def _display_order(node: CategoryNode) -> tuple[int, int]:
    return (node.display_order if node.display_order is not None else 0, node.id)


class CategoryTree:
    """Pure in-memory index over the node list. No I/O."""

    def __init__(self, nodes: list[CategoryNode]) -> None:
        self._by_id: dict[int, CategoryNode] = {node.id: node for node in nodes}
        self._children: dict[int, list[CategoryNode]] = {}
        self._roots: list[CategoryNode] = []
        for node in nodes:
            parent = node.parent_id
            if parent:
                self._children.setdefault(parent, []).append(node)
            else:
                self._roots.append(node)
        for siblings in self._children.values():
            siblings.sort(key=_display_order)
        self._roots.sort(key=_display_order)

    def __len__(self) -> int:
        return len(self._by_id)

    def get(self, category_id: int) -> CategoryNode | None:
        return self._by_id.get(int(category_id))

    def children(self, category_id: int) -> list[CategoryNode]:
        return list(self._children.get(int(category_id), ()))

    def roots(self) -> list[CategoryNode]:
        return list(self._roots)

    def path(self, category_id: int) -> list[CategoryNode]:
        """Root → leaf path, e.g. ``859`` → ``[7, 100, 859]``.

        Walks ``parent_id`` with a visited set, so a cyclical dataset cannot hang.
        """
        node = self.get(category_id)
        chain: list[CategoryNode] = []
        seen: set[int] = set()
        while node is not None and node.id not in seen:
            seen.add(node.id)
            chain.append(node)
            node = self.get(node.parent_id) if node.parent_id else None
        return list(reversed(chain))

    def search(self, name: str) -> list[CategoryNode]:
        """Case-insensitive substring match on the Japanese name."""
        needle = name.strip().lower()
        if not needle:
            return []
        return [node for node in self._by_id.values() if needle in node.name.lower()]


class Categories:
    """Blocking loader. The dataset is fetched once and kept for the process lifetime."""

    def __init__(self, transport: _Sender) -> None:
        self._transport = transport
        self._tree: CategoryTree | None = None

    @property
    def loaded(self) -> bool:
        return self._tree is not None

    def load(self, *, force: bool = False) -> CategoryTree:
        if self._tree is None or force:
            payload = self._transport.send(master_api.dataset(DATASET))
            self._tree = CategoryTree(nodes_from_dataset(payload))
        return self._tree

    def get(self, category_id: int) -> CategoryNode | None:
        return self.load().get(category_id)

    def children(self, category_id: int) -> list[CategoryNode]:
        return self.load().children(category_id)

    def path(self, category_id: int) -> list[CategoryNode]:
        return self.load().path(category_id)

    def roots(self) -> list[CategoryNode]:
        return self.load().roots()

    def search(self, name: str) -> list[CategoryNode]:
        return self.load().search(name)


class AsyncCategories:
    """Asyncio loader. ``await categories.load()`` first, or use the awaitable helpers."""

    def __init__(self, transport: _AsyncSender) -> None:
        self._transport = transport
        self._tree: CategoryTree | None = None

    @property
    def loaded(self) -> bool:
        return self._tree is not None

    async def load(self, *, force: bool = False) -> CategoryTree:
        if self._tree is None or force:
            payload = await self._transport.send(master_api.dataset(DATASET))
            self._tree = CategoryTree(nodes_from_dataset(payload))
        return self._tree

    async def get(self, category_id: int) -> CategoryNode | None:
        return (await self.load()).get(category_id)

    async def children(self, category_id: int) -> list[CategoryNode]:
        return (await self.load()).children(category_id)

    async def path(self, category_id: int) -> list[CategoryNode]:
        return (await self.load()).path(category_id)

    async def roots(self) -> list[CategoryNode]:
        return (await self.load()).roots()

    async def search(self, name: str) -> list[CategoryNode]:
        return (await self.load()).search(name)
