import datetime as dt
from decimal import Decimal
from typing import Literal

from ninja import Schema

from accounts.schemas import BoardMemberOut
from core.schemas import InputSchema
from stock.models import StockDirection, StockItemCategory, StockOperationReason

# The reasons of « Entrée ou sortie »: a stocktake and a delivery have their own
# screens.
EntryReason = Literal["purchase", "consumption", "adjustment"]


class StockItemIn(InputSchema):
    """An item as the board writes it: whole, every key required.

    Its values are checked by the model, whose messages are in French.
    """

    name: str
    category: StockItemCategory
    # Written after a quantity: empty, nothing is.
    unit: str
    threshold: Decimal
    step: Decimal
    # Any day of its month: the item keeps the month (« mai 2027 »).
    best_before: dt.date | None


class StockAdjustmentIn(InputSchema):
    """A click on minus or plus: the item's step, in or out."""

    direction: StockDirection


class StockLineIn(InputSchema):
    """A line of an entry or an exit: an item, and how much of it."""

    # The id of the item.
    item: int
    # Positive: the way of the operation signs it.
    quantity: Decimal


class StockOperationIn(InputSchema):
    """« Entrée ou sortie »: several items in or out at once, for one reason,
    every key required. A purchase comes in, a consumption goes out, an
    adjustment either way.
    """

    direction: StockDirection
    reason: EntryReason
    # Empty, the reason names the operation.
    label: str
    # The id of the event; None for none.
    event: int | None
    lines: list[StockLineIn]


class StockCountIn(InputSchema):
    """What a stocktake counted of an item."""

    # The id of the item.
    item: int
    counted: Decimal


class StocktakeIn(InputSchema):
    """« Faire l'inventaire »: the items counted, every key required. An item
    left out is not counted.
    """

    # Empty, « Inventaire » names it.
    label: str
    # The id of the event; None for none.
    event: int | None
    counts: list[StockCountIn]


class StockItemOut(Schema):
    """An item, as its form writes it."""

    id: int
    name: str
    category: StockItemCategory
    unit: str
    threshold: Decimal
    step: Decimal
    # The first of its month; None without one.
    best_before: dt.date | None


class StockedItemOut(Schema):
    """An item and where its stock stands."""

    item: StockItemOut
    # The sum of its movements.
    quantity: Decimal
    # Below its threshold, strictly (A19).
    low: bool
    # How full its bar is, in percent: the quantity against twice the
    # threshold, at most 100.
    level: int


class StockCountsOut(Schema):
    """How many items the stock holds, in all, low, and by category: the chips."""

    total: int
    low: int
    drinks: int
    food: int
    supplies: int
    lotto_raffle: int


class StockEventOut(Schema):
    """The event of an operation."""

    id: int
    title: str


class LastStocktakeOut(Schema):
    """The latest stocktake, which dates the stock's title."""

    created_at: dt.datetime
    # None for a stocktake of no event, or once its event is deleted.
    event: StockEventOut | None


class StockMovementItemOut(Schema):
    """The item a movement changed, as the summary of its operation names it."""

    id: int
    name: str
    unit: str


class StockMovementOut(Schema):
    """What an operation changed of one item."""

    item: StockMovementItemOut
    # Positive in, negative out.
    delta: Decimal


class StockOperationOut(Schema):
    """An operation of the stock, as « Mouvements récents » tells it."""

    id: int
    reason: StockOperationReason
    # Empty, the reason names the operation.
    label: str
    # None for an operation of no event, or once its event is deleted.
    event: StockEventOut | None
    # None once the account is deleted.
    author: BoardMemberOut | None
    created_at: dt.datetime
    # In the order they were written; none for a stocktake that found no difference.
    movements: list[StockMovementOut]


class StockOverviewOut(Schema):
    """The stock, item by item, and its figures: a bounded aggregate (A7)."""

    # By category, in the order of the chips, then by name.
    items: list[StockedItemOut]
    counts: StockCountsOut
    # None before the first stocktake.
    last_stocktake: LastStocktakeOut | None
    # The latest operations, the latest first: a click on minus or plus is one.
    recent_operations: list[StockOperationOut]


class LowStockItemOut(Schema):
    """An item below its threshold, as the bell names it."""

    id: int
    name: str
    unit: str
    quantity: Decimal
    threshold: Decimal
