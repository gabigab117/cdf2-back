"""What the Stock page shows: a bounded aggregate (A7), never paginated."""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from stock.models import StockItem, StockItemCategory, StockOperation, StockOperationReason
from stock.services.items import StockedItem, quantity_to_buy, stock_items, stocked
from stock.services.operations import recent_operations
from stock.services.orders import Order, orders_to_receive


@dataclass(frozen=True)
class ShoppingLine:
    """An item below its threshold, and what to buy of it."""

    item: StockItem
    quantity: Decimal


@dataclass(frozen=True)
class StockOverview:
    """The stock, item by item, and its figures."""

    items: list[StockedItem]
    # In all, low, and by category: the chips.
    counts: dict[str, int]
    last_stocktake: StockOperation | None
    recent_operations: list[StockOperation]
    # The items below their threshold, in the stock's order (7.3).
    shopping_list: list[ShoppingLine]
    # The orders to receive, then those received today (7.4).
    orders: list[Order]


def stock_overview() -> StockOverview:
    """Every item and where its stock stands, the figures of the chips, the
    latest stocktake, the latest operations, the shopping list, and the
    orders to receive.
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
        shopping_list=[
            ShoppingLine(
                item=entry.item,
                quantity=quantity_to_buy(entry.quantity, entry.item.threshold, entry.item.step),
            )
            for entry in items
            if entry.low
        ],
        orders=orders_to_receive(),
    )
