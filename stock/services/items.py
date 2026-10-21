"""The stock's items, as the board lists and writes them (A19).

An item's quantity is the sum of its movements, and it is low below its
threshold, strictly. Both are worked out by the database, for the stock and the
bell alike.
"""

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.db.models import Case, F, ProtectedError, QuerySet, Sum, Value, When

from stock.models import StockItem, StockItemCategory, StockOperation
from stock.schemas import StockItemIn
from stock.services.valuation import ValuedMovement, item_valuation, valued_movements

# Nothing in stock, written as a quantity is: to the hundredth.
NOTHING = Decimal("0.00")

# The stock's sort order: by category, as the chips go, then by name.
CATEGORY_SORT_ORDER = Case(
    *(
        When(category=category, then=Value(position))
        for position, category in enumerate(StockItemCategory.values)
    )
)


@dataclass(frozen=True)
class StockedItem:
    """An item and where its stock and its value stand."""

    item: StockItem
    quantity: Decimal
    low: bool
    # How full its bar is, in percent.
    level: int
    # Its weighted average cost, the value of what is in stock, and the unit
    # cost of its latest purchase paid (D16).
    average_cost: Decimal | None
    value: Decimal | None
    last_unit_cost: Decimal | None


@dataclass(frozen=True)
class ItemHistoryLine:
    """A movement of an item as its stock card tells it (« fiche de stock »):
    what moved, at what cost, and where the stock, its value and its average
    cost stood after it (D16).
    """

    operation: StockOperation
    delta: Decimal
    cost: Decimal | None
    unit_cost: Decimal | None
    value: Decimal | None
    unpriced: bool
    quantity_after: Decimal
    value_after: Decimal | None
    average_cost_after: Decimal | None


def stock_items() -> QuerySet[StockItem]:
    """The items with their quantity, and whether they are low, in the stock's
    order. The sum groups the rows: the order is given again.
    """
    return (
        StockItem.objects.annotate(quantity=Sum("movements__delta", default=NOTHING))
        .annotate(
            low=Case(When(quantity__lt=F("threshold"), then=Value(True)), default=Value(False))
        )
        .order_by(CATEGORY_SORT_ORDER, "name", "pk")
    )


def low_items() -> QuerySet[StockItem]:
    """The items below their threshold, in the stock's order: the bell lists them."""
    return stock_items().filter(low=True)


def stocked(item: StockItem, history: list[ValuedMovement]) -> StockedItem:
    """An item read by stock_items(), with its level, and its value from its
    movements valued (its history).
    """
    valuation = item_valuation(item, history)
    return StockedItem(
        item=item,
        quantity=item.quantity,
        low=item.low,
        level=level(item.quantity, item.threshold),
        average_cost=valuation.average_cost,
        value=valuation.value,
        last_unit_cost=valuation.last_unit_cost,
    )


def item_history(item: StockItem) -> list[ItemHistoryLine]:
    """« Fiche de stock »: the movements of an item, the latest first, each with
    its operation and its value. The whole item is replayed for any page of it.
    """
    history = valued_movements([item.pk]).get(item.pk, [])
    operations = StockOperation.objects.select_related("event").in_bulk(
        {movement.operation_id for movement in history}
    )
    return [
        ItemHistoryLine(
            operation=operations[movement.operation_id],
            delta=movement.delta,
            cost=movement.cost,
            unit_cost=movement.unit_cost,
            value=movement.value,
            unpriced=movement.unpriced,
            quantity_after=movement.quantity_after,
            value_after=movement.value_after,
            average_cost_after=movement.average_cost_after,
        )
        for movement in reversed(history)
    ]


def level(quantity: Decimal, threshold: Decimal) -> int:
    """How full an item's bar is, in percent: its quantity against its
    threshold, what the next event needs (A19), at most 100, rounded as the
    mockup does. Without a threshold, it is full while some is left.
    """
    if not threshold:
        return 100 if quantity > 0 else 0
    percent = (quantity * 100 / threshold).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return min(100, int(percent))


def quantity_to_buy(quantity: Decimal, threshold: Decimal, step: Decimal) -> Decimal:
    """What brings an item back to its threshold, rounded up to its step (A19):
    the shopping list buys by the pack.
    """
    steps = ((threshold - quantity) / step).to_integral_value(rounding=ROUND_CEILING)
    return steps * step


def create_item(data: StockItemIn) -> StockItem:
    """Add an item to the stock, with nothing in it yet."""
    return _save(StockItem(), data)


def update_item(item: StockItem, data: StockItemIn) -> StockItem:
    """Rewrite an item whole: its movements stay as they are."""
    return _save(item, data)


def delete_item(item: StockItem) -> None:
    """Delete an item that has never moved, nor been ordered: the history keeps
    the others.
    """
    # PROTECT refuses it before any deletion: the transaction stays usable.
    try:
        item.delete()
    except ProtectedError as error:
        raise ValidationError(
            f"Impossible de supprimer « {item.name} » : ses mouvements ou ses commandes le "
            "gardent dans l’historique. Mettez plutôt son seuil à 0, il ne sera plus signalé bas."
        ) from error


def _save(item: StockItem, data: StockItemIn) -> StockItem:
    item.name = data.name
    item.category = data.category
    item.unit = data.unit
    item.threshold = data.threshold
    item.step = data.step
    # To the month, as the first of it.
    item.best_before = data.best_before.replace(day=1) if data.best_before else None
    item.initial_cost = data.initial_cost
    item.full_clean()
    item.save()
    # Read again as the database rounds its numbers: « 24.00 » for « 24 ».
    item.refresh_from_db()
    return item
