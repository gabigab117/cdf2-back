"""The value of the stock (D16): each item at its weighted average cost,
recomputed at each entry, all taxes included.

The value is worked out from the movements, in the order they were recorded, as
the quantity is: none is stored, so correcting a cost, pricing a purchase or
undoing a delivery recomputes everything. No aggregate of the database takes a
moving average: each item's movements are read in one query, and replayed here.

The value is kept to the cent, and makes the average: a movement without a cost
moves its share of the value, so an exit that empties the stock takes it all.
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from stock.models import StockItem, StockMovement, StockOperationReason

CENT = Decimal("0.01")
# A unit cost, to the ten-thousandth: a cup costs less than a cent.
TEN_THOUSANDTH = Decimal("0.0001")
NO_VALUE = Decimal("0.00")

# The operations that bring goods in at a cost: their lines have one, or wait for it.
PRICED_REASONS = (StockOperationReason.PURCHASE, StockOperationReason.DELIVERY)


@dataclass(frozen=True)
class ValuedMovement:
    """A movement of an item, valued at the average cost of its time."""

    id: int
    operation_id: int
    reason: str
    # None for an operation of no event.
    event_id: int | None
    created_at: dt.datetime
    delta: Decimal
    # What its line cost; None for no purchase, or until it is known.
    cost: Decimal | None
    # What it brought in, positive, or took out, negative, to the cent: its cost
    # when it has one. None for a movement without one, of an item that has no
    # cost to start from.
    value: Decimal | None
    # A purchase or a delivery waiting for its cost: valued at the average.
    unpriced: bool
    quantity_after: Decimal
    value_after: Decimal | None
    # None once the stock is empty, or for an item not valued.
    average_cost_after: Decimal | None

    @property
    def unit_cost(self) -> Decimal | None:
        """The unit cost it moved at: its own for a purchase, the average for
        any other movement.
        """
        if self.value is None:
            return None
        return _unit(abs(self.value) / abs(self.delta))


@dataclass(frozen=True)
class ItemValuation:
    """Where an item's value stands."""

    # The value of what is in stock; None for an item not valued.
    value: Decimal | None
    # The weighted average cost; with nothing left, the latest one. None for an
    # item without any.
    average_cost: Decimal | None
    # The unit cost of its latest purchase paid; None before any.
    last_unit_cost: Decimal | None


# What a row of the replay reads of a movement and its operation.
Row = tuple[int, int, str, int | None, dt.datetime, Decimal, Decimal | None]


def valued_movements(item_ids: Iterable[int] | None = None) -> dict[int, list[ValuedMovement]]:
    """The movements of each item, of the items given or of all, in the order
    they were recorded, valued. An item without any movement has none.
    """
    # The movement's key orders nothing more: an item comes once per operation.
    movements = StockMovement.objects.order_by("operation__created_at", "operation_id")
    if item_ids is not None:
        movements = movements.filter(item_id__in=item_ids)
    rows: dict[int, list[Row]] = defaultdict(list)
    initial_costs: dict[int, Decimal | None] = {}
    for item_id, initial_cost, *row in movements.values_list(
        "item_id",
        "item__initial_cost",
        "pk",
        "operation_id",
        "operation__reason",
        "operation__event_id",
        "operation__created_at",
        "delta",
        "cost",
    ):
        rows[item_id].append(tuple(row))
        initial_costs[item_id] = initial_cost
    return {
        item_id: _replay(initial_costs[item_id], item_rows) for item_id, item_rows in rows.items()
    }


def item_valuation(item: StockItem, history: list[ValuedMovement]) -> ItemValuation:
    """An item's value, from its movements valued (its history)."""
    if not history:
        return ItemValuation(value=NO_VALUE, average_cost=item.initial_cost, last_unit_cost=None)
    latest_first = list(reversed(history))
    return ItemValuation(
        value=history[-1].value_after,
        average_cost=next(
            (m.average_cost_after for m in latest_first if m.average_cost_after is not None), None
        ),
        # A cost of 0 € is a prize given, not a purchase paid.
        last_unit_cost=next((m.unit_cost for m in latest_first if m.cost), None),
    )


def _replay(initial_cost: Decimal | None, rows: list[Row]) -> list[ValuedMovement]:
    """Value an item's movements, in their order.

    A movement that has its cost brings it in. Any other moves its share of
    the value, at the average cost of its time; when nothing is in stock, an
    entry comes at the latest average. Before any cost, the stock comes at the
    item's initial cost, or else at the unit cost of its first purchase paid
    above 0 €: without either, it is not valued, until the stock is empty
    again.
    """
    average = initial_cost if initial_cost is not None else _first_paid_unit_cost(rows)
    quantity = Decimal(0)
    # None while some of the stock has no cost to come at.
    value: Decimal | None = NO_VALUE
    valued = []
    for pk, operation_id, reason, event_id, created_at, delta, cost in rows:
        if cost is not None:
            moved = cost
        elif quantity > 0:
            moved = None if value is None else cents(value * delta / quantity)
        else:
            moved = None if average is None else cents(delta * average)
        quantity += delta
        if not quantity:
            # An empty stock is worth nothing, whatever came before.
            value = NO_VALUE
        elif value is not None:
            value = None if moved is None else value + moved
        average_after = None
        if value is not None and quantity > 0:
            average = value / quantity
            average_after = _unit(average)
        valued.append(
            ValuedMovement(
                id=pk,
                operation_id=operation_id,
                reason=reason,
                event_id=event_id,
                created_at=created_at,
                delta=delta,
                cost=cost,
                value=moved,
                unpriced=cost is None and reason in PRICED_REASONS,
                quantity_after=quantity,
                value_after=value,
                average_cost_after=average_after,
            )
        )
    return valued


def _first_paid_unit_cost(rows: list[Row]) -> Decimal | None:
    """The unit cost of an item's first purchase paid above 0 €: a prize given
    tells nothing of what the stock of before cost.
    """
    for *_movement, delta, cost in rows:
        if cost:
            return cost / delta
    return None


def cents(amount: Decimal) -> Decimal:
    """An amount to the cent, as the value of the stock keeps it."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _unit(amount: Decimal) -> Decimal:
    return amount.quantize(TEN_THOUSANDTH, rounding=ROUND_HALF_UP)
