"""The management control of a fiscal year (D16): what each event cost and
brought in once its goods are counted, what the stock was worth on 1 January
and on 31 December, and why the management results and the adjusted result of
the fiscal year differ.

An entry counts in the year of its date, an operation of the stock in the year
it was recorded, in Paris. The management result of an event is its income,
less its expenses, plus its stocked purchases (the share of its expenses gone
into stock), less the goods its operations consumed, at their average cost.

The stock changes by what its movements of the year moved, as the valuation
replays them: a purchase brings in its cost, any other movement takes out its
share at the average cost. The adjusted result, the result of the fiscal year
plus that change, is thus the sum of the management results, plus the purchases
of the year no expense of the year paid, less those an expense of the year paid
but another year recorded: the reconciliation tells each.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Sum
from django.utils import timezone

from events.models import Event
from stock.models import StockItem, StockItemCategory, StockOperationReason
from stock.services.items import NOTHING
from stock.services.overview import CategoryValue
from stock.services.valuation import NO_VALUE, PRICED_REASONS, ValuedMovement, valued_movements
from treasury.models import LedgerCategory, LedgerEntry, LedgerEntryKind
from treasury.services.results import ZERO, LedgerEvent, LedgerTotals, fiscal_year_results

# The goods of the bar: its supplies, such as the cups, are not in its margin.
BAR_CATEGORIES = (StockItemCategory.DRINKS, StockItemCategory.FOOD)
# A margin rate, to the thousandth: « 71,7 % ».
THOUSANDTH = Decimal("0.001")
# The totals of an event that has operations of the stock but no entry.
NO_ENTRIES = LedgerTotals(income=ZERO, expense=ZERO, count=0)


@dataclass(frozen=True)
class ManagementRow:
    """The management of an event, or of the general running (no event)."""

    event: LedgerEvent | None
    income: Decimal
    expense: Decimal
    # The share of its expenses of the year gone into stock.
    stocked_purchases: Decimal
    # What its operations of the year took out of the stock, at the average
    # cost, less what they brought back.
    consumption_cost: Decimal
    # Its bar income, less the drinks and food it consumed.
    bar_margin: Decimal
    # The bar margin over the bar income; None without any.
    margin_rate: Decimal | None
    # What its purchases of the year that no expense paid brought into stock.
    unlinked_purchases: Decimal

    @property
    def management_result(self) -> Decimal:
        return self.income - self.expense + self.stocked_purchases - self.consumption_cost


@dataclass(frozen=True)
class ManagementTotals:
    result: Decimal
    # The value of the stock on 1 January, and on 31 December, or today for
    # the current year.
    opening_value: Decimal
    closing_value: Decimal
    management_result: Decimal

    @property
    def stock_change(self) -> Decimal:
        return self.closing_value - self.opening_value

    @property
    def adjusted_result(self) -> Decimal:
        return self.result + self.stock_change


@dataclass(frozen=True)
class StockLoss:
    """What the stocktakes of no event found missing of an item over the year:
    above zero for a loss, below for goods found.
    """

    item: StockItem
    quantity: Decimal
    # None for an item not valued.
    value: Decimal | None


@dataclass(frozen=True)
class StockLosses:
    # The value of the losses of the items valued.
    total: Decimal
    # The largest loss first.
    items: list[StockLoss]


@dataclass(frozen=True)
class ManagementStock:
    # The value at the end of the year, in the order of the chips.
    categories: list[CategoryValue]
    losses: StockLosses


@dataclass(frozen=True)
class Reconciliation:
    """From the sum of the management results to the adjusted result: each
    line adds to the one before.
    """

    management_result: Decimal
    # The purchases of the year no expense paid.
    unlinked_purchases: Decimal
    # The purchases of the year an expense of another year paid.
    paid_another_year: Decimal
    # Less the purchases of another year an expense of the year paid.
    recorded_another_year: Decimal

    @property
    def adjusted_result(self) -> Decimal:
        return (
            self.management_result
            + self.unlinked_purchases
            + self.paid_another_year
            + self.recorded_another_year
        )


@dataclass(frozen=True)
class ManagementControls:
    """What the figures of the year still wait for."""

    # Purchases and deliveries of the year waiting for the cost of a line.
    unpriced_purchases: int
    # Purchases and deliveries of the year above 0 € that no expense paid.
    unlinked_purchases: int
    # Items whose stock has no cost to come at, at the end of the year.
    unvalued_items: int


@dataclass(frozen=True)
class FiscalYearManagement:
    year: int
    years: list[int]
    events: list[ManagementRow]
    general: ManagementRow
    totals: ManagementTotals
    stock: ManagementStock
    reconciliation: Reconciliation
    controls: ManagementControls


class _StockYear:
    """What the movements of the stock tell of a fiscal year, item by item."""

    def __init__(self, year: int) -> None:
        self.year = year
        self.opening_value = NO_VALUE
        self.categories = dict.fromkeys(StockItemCategory.values, NO_VALUE)
        self.unvalued_items = 0
        # By event, None for the general running.
        self.consumption: defaultdict[int | None, Decimal] = defaultdict(lambda: NO_VALUE)
        self.bar_consumption: defaultdict[int | None, Decimal] = defaultdict(lambda: NO_VALUE)
        # The purchases and deliveries, by operation, whatever their year: what
        # each brought into stock, its cost when an expense paid it, and the
        # year it was recorded. Those of the year: their event, and those
        # waiting for the cost of a line.
        self.purchases: defaultdict[int, Decimal] = defaultdict(lambda: NO_VALUE)
        self.recorded_in: dict[int, int] = {}
        self.events: dict[int, int | None] = {}
        self.unpriced: set[int] = set()
        self.losses: list[StockLoss] = []

    def add(self, item: StockItem, history: list[ValuedMovement]) -> None:
        opening: Decimal | None = NO_VALUE
        closing: Decimal | None = NO_VALUE
        lost_quantity = NOTHING
        lost_value: Decimal | None = NO_VALUE
        for movement in history:
            recorded = timezone.localtime(movement.created_at).year
            moved = movement.value or NO_VALUE
            priced = movement.reason in PRICED_REASONS
            if priced:
                self.purchases[movement.operation_id] += moved
                self.recorded_in[movement.operation_id] = recorded
            if recorded < self.year:
                opening = movement.value_after
            if recorded <= self.year:
                closing = movement.value_after
            if recorded != self.year:
                continue
            if priced:
                self.events[movement.operation_id] = movement.event_id
                if movement.unpriced:
                    self.unpriced.add(movement.operation_id)
                continue
            self.consumption[movement.event_id] -= moved
            if item.category in BAR_CATEGORIES:
                self.bar_consumption[movement.event_id] -= moved
            if movement.reason == StockOperationReason.STOCKTAKE and movement.event_id is None:
                lost_quantity -= movement.delta
                lost_value = (
                    None
                    if movement.value is None or lost_value is None
                    else lost_value - movement.value
                )
        self.opening_value += opening or NO_VALUE
        if closing is None:
            self.unvalued_items += 1
        else:
            self.categories[item.category] += closing
        if lost_quantity or lost_value:
            self.losses.append(StockLoss(item=item, quantity=lost_quantity, value=lost_value))


def fiscal_year_management(year: int) -> FiscalYearManagement:
    """The management control of a fiscal year: a row for each event that has
    entries or operations in it, the first to start first, then the general
    running; the totals, the stock, the reconciliation and the controls.
    """
    results = fiscal_year_results(year)
    stock = _StockYear(year)
    items = StockItem.objects.in_bulk()
    for item_id, history in valued_movements().items():
        stock.add(items[item_id], history)
    # The stock purchase each expense paid, whatever their years: the year
    # and the event of the expense.
    paid = {
        operation: (date.year, event)
        for operation, date, event in LedgerEntry.objects.filter(
            stock_purchase__isnull=False
        ).values_list("stock_purchase", "date", "event")
    }
    bar_income = dict(
        LedgerEntry.objects.filter(
            date__year=year, kind=LedgerEntryKind.INCOME, category=LedgerCategory.BAR
        )
        .values("event")
        .annotate(total=Sum("amount"))
        .order_by()
        .values_list("event", "total")
    )
    # A purchase an expense paid brought in its costs, every one known: its
    # value is what the expense put in stock.
    stocked: defaultdict[int | None, Decimal] = defaultdict(lambda: NO_VALUE)
    unlinked: defaultdict[int | None, Decimal] = defaultdict(lambda: NO_VALUE)
    paid_another_year = recorded_another_year = NO_VALUE
    unlinked_count = 0
    for operation, value in stock.purchases.items():
        paid_year, paid_event = paid.get(operation, (None, None))
        of_the_year = stock.recorded_in[operation] == year
        if paid_year == year:
            stocked[paid_event] += value
            if not of_the_year:
                recorded_another_year -= value
        elif of_the_year:
            if paid_year is not None:
                paid_another_year += value
            else:
                unlinked[stock.events[operation]] += value
                # A lot given at 0 € waits for no expense.
                if value > 0:
                    unlinked_count += 1

    def row(event: LedgerEvent | None, totals: LedgerTotals) -> ManagementRow:
        key = event.id if event else None
        bar = bar_income.get(key, ZERO)
        margin = bar - stock.bar_consumption[key]
        return ManagementRow(
            event=event,
            income=totals.income,
            expense=totals.expense,
            stocked_purchases=stocked[key],
            consumption_cost=stock.consumption[key],
            bar_margin=margin,
            margin_rate=(margin / bar).quantize(THOUSANDTH, rounding=ROUND_HALF_UP)
            if bar
            else None,
            unlinked_purchases=unlinked[key],
        )

    with_entries = {result.event.id for result in results.events}
    without_entries = {*stock.consumption, *stock.events.values()} - {None, *with_entries}
    others = [
        LedgerEvent(pk, title, starts_at)
        for pk, title, starts_at in Event.objects.filter(pk__in=without_entries).values_list(
            "pk", "title", "starts_at"
        )
    ]
    events = sorted(
        [row(result.event, result) for result in results.events]
        + [row(event, NO_ENTRIES) for event in others],
        key=lambda entry: (entry.event.starts_at, entry.event.id),
    )
    general = row(None, results.general)
    management_result = sum((entry.management_result for entry in [*events, general]), ZERO)
    return FiscalYearManagement(
        year=year,
        years=results.years,
        events=events,
        general=general,
        totals=ManagementTotals(
            result=results.totals.result,
            opening_value=stock.opening_value,
            closing_value=sum(stock.categories.values(), NO_VALUE),
            management_result=management_result,
        ),
        stock=ManagementStock(
            categories=[
                CategoryValue(category=key, value=value) for key, value in stock.categories.items()
            ],
            losses=StockLosses(
                total=sum((loss.value for loss in stock.losses if loss.value), NO_VALUE),
                items=sorted(
                    stock.losses,
                    key=lambda loss: (-(loss.value or NO_VALUE), loss.item.name),
                ),
            ),
        ),
        reconciliation=Reconciliation(
            management_result=management_result,
            unlinked_purchases=sum(unlinked.values(), NO_VALUE),
            paid_another_year=paid_another_year,
            recorded_another_year=recorded_another_year,
        ),
        controls=ManagementControls(
            unpriced_purchases=len(stock.unpriced),
            unlinked_purchases=unlinked_count,
            unvalued_items=stock.unvalued_items,
        ),
    )
