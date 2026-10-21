import datetime as dt
from decimal import Decimal
from typing import Literal

from django.db.models import Q
from ninja import FilterSchema, Schema

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
    # The unit cost of the stock of before the costs (D16); None for none.
    initial_cost: Decimal | None


class StockAdjustmentIn(InputSchema):
    """A click on minus or plus: the item's step, in or out."""

    direction: StockDirection


class StockLineIn(InputSchema):
    """A line of an entry or an exit: an item, and how much of it."""

    # The id of the item.
    item: int
    # Positive: the direction of the operation signs it.
    quantity: Decimal
    # What the line cost, all taxes included: a purchase's alone (D16). None
    # while unknown.
    cost: Decimal | None = None


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


class StockOperationFilters(FilterSchema):
    """The operations the list keeps."""

    # The purchases and deliveries waiting for the cost of a line (D16).
    unpriced: bool = False

    def filter_unpriced(self, value: bool) -> Q:
        # Called even when the filter is left out: false keeps every operation.
        return Q(unpriced=True) if value else Q()


class StockCostIn(InputSchema):
    """What a line of a purchase or a delivery cost."""

    # The id of the item of the line.
    item: int
    # All taxes included; None while unknown.
    cost: Decimal | None


class StockCostsIn(InputSchema):
    """« Compléter les prix », « Corriger les prix »: what each line of a purchase
    or a delivery cost, every line at once (D16).
    """

    lines: list[StockCostIn]


class OrderLineIn(InputSchema):
    """A line of an order: an item, and how much of it comes."""

    # The id of the item.
    item: int
    quantity: Decimal


class OrderLinesIn(InputSchema):
    """The lines of an order, all at once: without any, the order brings
    nothing to the stock.
    """

    lines: list[OrderLineIn]


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
    # To the ten-thousandth; None without one.
    initial_cost: Decimal | None


class StockedItemOut(Schema):
    """An item and where its stock and its value stand."""

    item: StockItemOut
    # The sum of its movements.
    quantity: Decimal
    # Below its threshold, strictly (A19).
    low: bool
    # How full its bar is, in percent: the quantity against the threshold, at
    # most 100.
    level: int
    # Its weighted average cost, to the ten-thousandth (D16); with nothing left,
    # the latest one. None for an item that has no cost to come at.
    average_cost: Decimal | None
    # The value of what is in stock, to the cent; None for an item not valued.
    value: Decimal | None
    # The unit cost of its latest purchase paid; None before any.
    last_unit_cost: Decimal | None


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
    """An item as a line names it: the movement of an operation, a line of the
    shopping list.
    """

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
    # A purchase or a delivery waiting for the cost of a line (D16).
    unpriced: bool


class StockOperationLineOut(Schema):
    """A line of an operation, valued at the cost of its time (D16)."""

    item: StockMovementItemOut
    # Positive in, negative out.
    delta: Decimal
    # What the line of a purchase or a delivery cost; None while unknown.
    cost: Decimal | None
    # The unit cost it moved at, to the ten-thousandth; None for an item whose
    # stock has no cost to come at.
    unit_cost: Decimal | None
    # What it brought in, positive, or took out, negative, to the cent; None
    # likewise.
    value: Decimal | None
    # A line of a purchase or a delivery waiting for its cost.
    unpriced: bool


class StockOperationDetailOut(Schema):
    """An operation of the stock, as its page shows it: its lines valued."""

    id: int
    reason: StockOperationReason
    # Empty, the reason names the operation.
    label: str
    # None for an operation of no event, or once its event is deleted.
    event: StockEventOut | None
    # None once the account is deleted.
    author: BoardMemberOut | None
    created_at: dt.datetime
    # A purchase or a delivery waiting for the cost of a line.
    unpriced: bool
    # A purchase or a delivery: the costs of its lines are completed or corrected.
    priceable: bool
    # What the lines that have a cost cost, in all, to the cent.
    cost: Decimal
    # In the order they were written.
    lines: list[StockOperationLineOut]


class UnpricedPurchaseOut(Schema):
    """A purchase or a delivery waiting for the cost of a line, as the bell names it."""

    id: int
    reason: StockOperationReason
    # Empty, the reason names it.
    label: str
    created_at: dt.datetime
    # None once the account is deleted.
    author: BoardMemberOut | None


class ShoppingLineOut(Schema):
    """An item below its threshold, and what brings it back to it, rounded up
    to its step (A19).
    """

    item: StockMovementItemOut
    quantity: Decimal
    # At the unit cost of its latest purchase paid (D16); None before any.
    estimated_cost: Decimal | None


class ShoppingListEstimatedCostOut(Schema):
    """What the shopping list should cost (its budget), of its lines that have a
    cost.
    """

    total: Decimal
    # The lines no purchase paid tells the cost of.
    unpriced_lines: int


class StockCategoryValueOut(Schema):
    """The value of a category's items."""

    category: StockItemCategory
    value: Decimal


class StockValuationOut(Schema):
    """The value of the stock (D16): its items at their weighted average cost."""

    # Of the items that have one, to the cent.
    value: Decimal
    # In the order of the chips, each one, even of no value.
    categories: list[StockCategoryValueOut]
    # The items whose stock has no cost to come at.
    unvalued_items: int
    # The purchases and deliveries waiting for the cost of a line.
    unpriced_purchases: int


class OrderLineOut(Schema):
    """A line of an order: « Bonbons assortis +12 kg »."""

    item: StockMovementItemOut
    quantity: Decimal


class StockDeliveryOut(Schema):
    """When, and by whom, an order was received."""

    created_at: dt.datetime
    # None once the account is deleted.
    author: BoardMemberOut | None


class StockOrderOut(Schema):
    """An order of the stock (7.4): its document, its lines and its delivery."""

    # The id of its document.
    id: int
    title: str
    # The supplier.
    issuer: str
    # None for an order without one.
    delivery_date: dt.date | None
    # None for an order of no event.
    event: StockEventOut | None
    validated: bool
    lines: list[OrderLineOut]
    # None until it is received.
    delivery: StockDeliveryOut | None
    # Received today: « Annuler » undoes it until midnight.
    undoable: bool


class StockOverviewOut(Schema):
    """The stock, item by item, and its figures: a bounded aggregate (A7)."""

    # By category, in the order of the chips, then by name.
    items: list[StockedItemOut]
    counts: StockCountsOut
    # None before the first stocktake.
    last_stocktake: LastStocktakeOut | None
    # The latest operations, the latest first: a click on minus or plus is one.
    recent_operations: list[StockOperationOut]
    # The items below their threshold, in the stock's order.
    shopping_list: list[ShoppingLineOut]
    shopping_list_estimated_cost: ShoppingListEstimatedCostOut
    # The orders validated with lines, not received yet, the first delivered
    # first; then those received today.
    orders: list[StockOrderOut]
    valuation: StockValuationOut


class LowStockItemOut(Schema):
    """An item below its threshold, as the bell names it."""

    id: int
    name: str
    unit: str
    quantity: Decimal
    threshold: Decimal
