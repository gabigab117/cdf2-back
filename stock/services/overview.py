"""What the Stock page shows: a bounded aggregate (A7), never paginated."""

from collections import Counter
from dataclasses import dataclass

from stock.models import StockItemCategory, StockOperation, StockOperationReason
from stock.services.items import StockedItem, stock_items, stocked
from stock.services.operations import recent_operations


@dataclass(frozen=True)
class StockOverview:
    """The stock, item by item, and its figures."""

    items: list[StockedItem]
    # In all, low, and by category: the chips.
    counts: dict[str, int]
    last_stocktake: StockOperation | None
    recent_operations: list[StockOperation]


def stock_overview() -> StockOverview:
    """Every item and where its stock stands, the figures of the chips, the
    latest stocktake, and the latest operations.
    """
    items = [stocked(item) for item in stock_items()]
    by_category = Counter(entry.item.category for entry in items)
    return StockOverview(
        items=items,
        counts={
            "total": len(items),
            "low": sum(entry.low for entry in items),
            **{category: by_category[category] for category in StockItemCategory.values},
        },
        last_stocktake=StockOperation.objects.filter(reason=StockOperationReason.STOCKTAKE)
        .select_related("event")
        .first(),
        recent_operations=recent_operations(),
    )
