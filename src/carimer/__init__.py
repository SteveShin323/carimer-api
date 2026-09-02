"""carimer — unofficial anonymous-scope client for the Mercari (JP) private API.

Public API per ``docs/03-architecture.md`` §3.9.

    from carimer import Client, SearchQuery, Sort, Order
    with Client() as client:
        page = client.search(SearchQuery("iphone 15").price(10_000, 80_000))
"""

from carimer._version import __version__
from carimer.catalog.categories import AsyncCategories, Categories, CategoryTree
from carimer.catalog.facets_client import AsyncFacetsClient, FacetsClient
from carimer.client import AsyncClient, Client
from carimer.models.enums import (
    Condition,
    ItemKind,
    ItemType,
    Order,
    ShippingMethod,
    ShippingPayer,
    Sort,
    Status,
    ThumbnailType,
)
from carimer.models.facets import Brand, CategoryNode, Facet, FacetSection, Size, SizeGroup
from carimer.models.item import ConvertedPrice, EmbeddedSeller, Item, ItemAttribute, ItemComment
from carimer.models.misc import DesiredPriceInfo, SimilarItem, Suggestion
from carimer.models.profile import Badge, Profile, Review, SellerItem
from carimer.models.search import Auction, QuerySuggestChip, SearchItem, SearchPage
from carimer.models.shops import Shop, ShopsProduct, ShopsVariant
from carimer.search.attributes import (
    AsyncAttributeResolver,
    AttributeFilter,
    AttributeResolver,
    AttributeSection,
)
from carimer.search.query import SearchQuery
from carimer.transport.base import TransportOptions
from carimer.transport.errors import (
    AuthError,
    BadRequestError,
    BlockedError,
    CarimerError,
    NotAcceptableError,
    NotFoundError,
    ParseError,
    RateLimitedError,
    ShopsItemError,
    TransportError,
    UnknownFacetValue,
)

__all__ = [
    "AsyncAttributeResolver",
    "AsyncCategories",
    "AsyncClient",
    "AsyncFacetsClient",
    "AttributeFilter",
    "AttributeResolver",
    "AttributeSection",
    "Auction",
    "AuthError",
    "BadRequestError",
    "Badge",
    "BlockedError",
    "Brand",
    "CarimerError",
    "Categories",
    "CategoryNode",
    "CategoryTree",
    "Client",
    "Condition",
    "ConvertedPrice",
    "DesiredPriceInfo",
    "EmbeddedSeller",
    "Facet",
    "FacetSection",
    "FacetsClient",
    "Item",
    "ItemAttribute",
    "ItemComment",
    "ItemKind",
    "ItemType",
    "NotAcceptableError",
    "NotFoundError",
    "Order",
    "ParseError",
    "Profile",
    "QuerySuggestChip",
    "RateLimitedError",
    "Review",
    "SearchItem",
    "SearchPage",
    "SearchQuery",
    "SellerItem",
    "ShippingMethod",
    "ShippingPayer",
    "Shop",
    "ShopsItemError",
    "ShopsProduct",
    "ShopsVariant",
    "SimilarItem",
    "Size",
    "SizeGroup",
    "Sort",
    "Status",
    "Suggestion",
    "ThumbnailType",
    "TransportError",
    "TransportOptions",
    "UnknownFacetValue",
    "__version__",
]
