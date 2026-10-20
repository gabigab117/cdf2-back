import datetime as dt
from decimal import Decimal

from ninja import Schema

from core.schemas import InputSchema
from stock.models import StockDirection, StockItemCategory


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


class StockOverviewOut(Schema):
    """The stock, item by item, and its figures: a bounded aggregate (A7)."""

    # By category, in the order of the chips, then by name.
    items: list[StockedItemOut]
    counts: StockCountsOut
    # None before the first stocktake.
    last_stocktake: LastStocktakeOut | None


class LowStockItemOut(Schema):
    """An item below its threshold, as the bell names it."""

    id: int
    name: str
    unit: str
    quantity: Decimal
    threshold: Decimal
