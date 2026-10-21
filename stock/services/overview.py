"""What the Stock page shows: a bounded aggregate (A7), never paginated."""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from stock.models import StockItem, StockItemCategory, StockOperation, StockOperationReason
from stock.services.items import StockedItem, quantity_to_buy, stock_items, stocked
from stock.services.operations import recent_operations
from stock.services.orders import Order, orders_to_receive
from stock.services.valuation import NO_VALUE, ValuedMovement, cents, valued_movements


@dataclass(frozen=True)
class ShoppingLine:
    """An item below its threshold, and what to buy of it."""

    item: StockItem
    quantity: Decimal
    # At the unit cost of its latest purchase paid (D16); None before any.
    estimated_cost: Decimal | None


@dataclass(frozen=True)
class ShoppingListEstimatedCost:
    """What the shopping list should cost (its budget), and how many of its
    lines no purchase paid tells the cost of.
    """

    total: Decimal
    unpriced_lines: int


@dataclass(frozen=True)
class CategoryValue:
    """The value of a category's items."""

    category: str
    value: Decimal


@dataclass(frozen=True)
class StockValuation:
    """The value of the stock (D16), of the items that have one."""

    value: Decimal
    # In the order of the chips.
    categories: list[CategoryValue]
    # Items whose stock has no cost to come at.
    unvalued_items: int
    # Purchases and deliveries waiting for the cost of a line.
    unpriced_purchases: int


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
    shopping_list_estimated_cost: ShoppingListEstimatedCost
    # The orders to receive, then those received today (7.4).
    orders: list[Order]
    valuation: StockValuation


def stock_overview() -> StockOverview:
    """Every item and where its stock and its value stand, the figures of the
    chips, the latest stocktake, the latest operations, the shopping list and
    its cost, the orders to receive, and the value of the stock.
    """
    histories = valued_movements()
    items = [stocked(item, histories.get(item.pk, [])) for item in stock_items()]
    by_category = Counter(entry.item.category for entry in items)
    shopping_list = [_shopping_line(entry) for entry in items if entry.low]
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
        shopping_list=shopping_list,
        shopping_list_estimated_cost=ShoppingListEstimatedCost(
            total=sum(
                (line.estimated_cost for line in shopping_list if line.estimated_cost is not None),
                NO_VALUE,
            ),
            unpriced_lines=sum(line.estimated_cost is None for line in shopping_list),
        ),
        orders=orders_to_receive(),
        valuation=_valuation(items, histories),
    )


def _shopping_line(entry: StockedItem) -> ShoppingLine:
    """What to buy of a low item, and at what cost."""
    quantity = quantity_to_buy(entry.quantity, entry.item.threshold, entry.item.step)
    unit_cost = entry.last_unit_cost
    return ShoppingLine(
        item=entry.item,
        quantity=quantity,
        estimated_cost=None if unit_cost is None else cents(quantity * unit_cost),
    )


def _valuation(
    items: list[StockedItem], histories: dict[int, list[ValuedMovement]]
) -> StockValuation:
    """The value of the stock, in all and by category, and what it cannot tell yet."""
    values = dict.fromkeys(StockItemCategory.values, NO_VALUE)
    for entry in items:
        if entry.value is not None:
            values[entry.item.category] += entry.value
    return StockValuation(
        value=sum(values.values(), NO_VALUE),
        categories=[CategoryValue(category=key, value=value) for key, value in values.items()],
        unvalued_items=sum(entry.value is None for entry in items),
        unpriced_purchases=len(
            {
                movement.operation_id
                for history in histories.values()
                for movement in history
                if movement.unpriced
            }
        ),
    )
