import datetime as dt
from decimal import Decimal
from typing import Annotated

from django.db.models import Q
from ninja import Field, FilterLookup, FilterSchema, Schema

from accounts.schemas import BoardMemberOut
from core.schemas import InputSchema
from stock.models import StockOperationReason
from stock.schemas import StockCategoryValueOut, StockMovementItemOut
from treasury.models import (
    LedgerCategory,
    LedgerEntryKind,
    LedgerPaymentMethod,
    LedgerReceiptState,
    ReimbursementMethod,
)

# A calendar year, as a fiscal year is (A18): the dates of the database go from
# year 1 to 9999.
FiscalYear = Annotated[int, Field(ge=1, le=9999)]


class LedgerEntryIn(InputSchema):
    """A ledger entry as the board corrects it: whole, every key required.

    Its values are checked by the model and the service, whose messages are in
    French. Its amount is positive: its kind tells income from expense.
    """

    date: dt.date
    kind: LedgerEntryKind
    label: str
    amount: Decimal
    category: LedgerCategory
    payment_method: LedgerPaymentMethod
    # The id of the board member who paid an advance; None for any other entry.
    advanced_by: int | None
    # The id of the event; None for the committee's general running.
    event: int | None
    supplier: str
    note: str


class NewLedgerEntryIn(LedgerEntryIn):
    """A ledger entry as the board records it, from a form: a field left empty
    is not sent, and takes its default.
    """

    advanced_by: int | None = None
    event: int | None = None
    supplier: str = ""
    note: str = ""


class LedgerEntryFilters(FilterSchema):
    """The entries the journal keeps: every filter given applies."""

    year: Annotated[FiscalYear | None, FilterLookup("date__year")] = None
    # The id of an event.
    event: int | None = None
    # The entries of the committee's general running, without an event.
    general: bool = False
    # Every year's entries whose receipt stands so, such as those missing one.
    receipt_state: LedgerReceiptState | None = None
    # Every year's advances the committee still owes.
    to_reimburse: bool = False

    def filter_general(self, value: bool) -> Q:
        # Called even when the filter is left out: false keeps every entry.
        return Q(event__isnull=True) if value else Q()

    def filter_to_reimburse(self, value: bool) -> Q:
        # Called even when the filter is left out: false keeps every entry.
        if not value:
            return Q()
        return Q(payment_method=LedgerPaymentMethod.ADVANCE, reimbursed_on__isnull=True)


class StockPurchaseLineIn(InputSchema):
    """A line of the purchase an expense puts in stock: an item, how much of it,
    and what it cost, all taxes included (D16).
    """

    # The id of the item.
    item: int
    quantity: Decimal
    cost: Decimal


class StockPurchaseIn(InputSchema):
    """« Mettre en stock »: the purchase an expense paid, its lines with their
    costs, every key required.
    """

    lines: list[StockPurchaseLineIn]


class ExistingPurchaseLineIn(InputSchema):
    """What a line of a purchase recorded in the stock cost."""

    # The id of the item of the line.
    item: int
    cost: Decimal


class ExistingPurchaseIn(InputSchema):
    """« Achat déjà saisi »: a purchase or a delivery recorded in the stock, paid
    by the expense, the cost of each of its lines given.
    """

    # The id of the stock operation.
    operation: int
    lines: list[ExistingPurchaseLineIn]


class ReimbursementIn(InputSchema):
    """How the committee paid an advance back: every key required."""

    reimbursed_on: dt.date
    reimbursement_method: ReimbursementMethod


class InvoiceExpenseIn(InputSchema):
    """What an invoice does not tell of its expense, as the member types it:
    every key required.
    """

    paid_on: dt.date
    label: str
    category: LedgerCategory
    payment_method: LedgerPaymentMethod
    # The id of the board member who paid an advance; None for any other expense.
    advanced_by: int | None


class InvoiceAttachIn(InputSchema):
    """The expense, already entered, an invoice proves."""

    # The id of an expense without a receipt.
    entry: int


class FiscalYearQuery(Schema):
    year: FiscalYear


class LedgerEventOut(Schema):
    """The event of an entry, or of a result."""

    id: int
    title: str
    starts_at: dt.datetime


class LedgerReceiptOut(Schema):
    """The document that proves an entry, as its viewer opens it."""

    id: int
    title: str
    original_name: str
    # In bytes.
    size: int


class LedgerStockPurchaseOut(Schema):
    """The stock purchase an expense paid (D16)."""

    id: int
    reason: StockOperationReason
    # Empty, the reason names it.
    label: str
    created_at: dt.datetime


class LedgerEntryOut(Schema):
    """An entry of the journal, as its line and its page show it."""

    id: int
    date: dt.date
    kind: LedgerEntryKind
    label: str
    amount: Decimal
    category: LedgerCategory
    payment_method: LedgerPaymentMethod
    # None for an entry that is not an advance, and once its account is deleted.
    advanced_by: BoardMemberOut | None
    # None until the advance is paid back.
    reimbursed_on: dt.date | None
    reimbursement_method: ReimbursementMethod | None
    # None for the committee's general running.
    event: LedgerEventOut | None
    supplier: str
    note: str
    # None once the account is deleted.
    created_by: BoardMemberOut | None
    created_at: dt.datetime
    receipt: LedgerReceiptOut | None
    receipt_state: LedgerReceiptState
    # The member to ask for a missing receipt: who advanced the expense, or
    # else who recorded it; None once both accounts are deleted.
    contact: BoardMemberOut | None
    # The stock purchase an expense paid (D16); None for none.
    stock_purchase: LedgerStockPurchaseOut | None
    # What that purchase cost: the share of the expense gone into stock; and
    # what is left of the expense, a direct charge. None without a purchase.
    stocked_cost: Decimal | None
    unstocked_cost: Decimal | None


class UnpaidInvoiceOut(Schema):
    """An invoice « à régler », as the bell and the treasury assistant name it."""

    id: int
    title: str
    issuer: str
    amount: Decimal | None
    due_date: dt.date | None
    # Its due date has passed.
    overdue: bool


class LedgerTotalsOut(Schema):
    """What came in and went out, the result, and over how many entries."""

    income: Decimal
    expense: Decimal
    # Income less expense.
    result: Decimal
    count: int


class LedgerEventResultOut(LedgerTotalsOut):
    """The totals of an event that has entries in the fiscal year."""

    event: LedgerEventOut


class FiscalYearResultsOut(Schema):
    """A fiscal year's totals, by event then without one: a bounded aggregate (A7)."""

    year: int
    # The years that have entries, and the current one, the latest first.
    years: list[int]
    totals: LedgerTotalsOut
    # The events that have entries, the first to start first.
    events: list[LedgerEventResultOut]
    # The entries of the committee's general running.
    general: LedgerTotalsOut


class LedgerCategoryTotalOut(Schema):
    """What a category brought in, or cost, over a fiscal year."""

    category: LedgerCategory
    total: Decimal
    count: int


class ManagementRowOut(Schema):
    """The management of an event over a fiscal year, or of the general running
    (D16): its result once its goods are counted.
    """

    # None for the general running.
    event: LedgerEventOut | None
    income: Decimal
    expense: Decimal
    # The share of its expenses gone into stock.
    stocked_purchases: Decimal
    # What its operations took out of the stock, at the average cost, less
    # what they brought back.
    consumption_cost: Decimal
    # Income less expense, plus the stocked purchases, less the consumption.
    management_result: Decimal
    # Its bar income less the drinks and food it consumed.
    bar_margin: Decimal
    # The bar margin over the bar income, to the thousandth; None without any.
    margin_rate: Decimal | None
    # What its purchases of the year that no expense paid brought into stock.
    unlinked_purchases: Decimal


class ManagementTotalsOut(Schema):
    """The results of a fiscal year, and what its stock changed of them."""

    result: Decimal
    # The value of the stock on 1 January, and on 31 December, or today for
    # the current year.
    opening_value: Decimal
    closing_value: Decimal
    stock_change: Decimal
    # The result plus the stock change.
    adjusted_result: Decimal
    # The sum of the management results.
    management_result: Decimal


class StockLossOut(Schema):
    """What the stocktakes of no event found missing of an item over the year:
    above zero for a loss, below for goods found.
    """

    item: StockMovementItemOut
    quantity: Decimal
    # None for an item not valued.
    value: Decimal | None


class StockLossesOut(Schema):
    # The value of the losses of the items valued.
    total: Decimal
    # The largest loss first.
    items: list[StockLossOut]


class ManagementStockOut(Schema):
    # The value at the end of the year, in the order of the chips.
    categories: list[StockCategoryValueOut]
    losses: StockLossesOut


class ReconciliationOut(Schema):
    """From the management results to the adjusted result: each line adds to
    the one before.
    """

    management_result: Decimal
    # The purchases of the year no expense paid.
    unlinked_purchases: Decimal
    # The purchases of the year an expense of another year paid.
    paid_another_year: Decimal
    # Below zero: the purchases of another year an expense of the year paid.
    recorded_another_year: Decimal
    adjusted_result: Decimal


class ManagementControlsOut(Schema):
    """What the figures of the year still wait for."""

    # Purchases and deliveries of the year waiting for the cost of a line.
    unpriced_purchases: int
    # Purchases and deliveries of the year above 0 € that no expense paid.
    unlinked_purchases: int
    # Items whose stock has no cost to come at, at the end of the year.
    unvalued_items: int


class ManagementOut(Schema):
    """« Contrôle de gestion » (D16): a fiscal year's management, by event then
    without one, its stock and its reconciliation, a bounded aggregate (A7).
    """

    year: int
    # The years that have entries, and the current one, the latest first.
    years: list[int]
    # The events that have entries or operations, the first to start first.
    events: list[ManagementRowOut]
    general: ManagementRowOut
    totals: ManagementTotalsOut
    stock: ManagementStockOut
    reconciliation: ReconciliationOut
    controls: ManagementControlsOut


class GeneralMeetingReportOut(Schema):
    """The report of a fiscal year for the general meeting: a bounded aggregate (A7)."""

    year: int
    totals: LedgerTotalsOut
    # The events that have entries, the first to start first.
    events: list[LedgerEventResultOut]
    # The entries of the committee's general running.
    general: LedgerTotalsOut
    # The categories that have entries, in the order of the form.
    income_categories: list[LedgerCategoryTotalOut]
    expense_categories: list[LedgerCategoryTotalOut]
    # The expenses of the year missing their receipt, the oldest first.
    missing_receipts: list[LedgerEntryOut]
    # The stock and the management of the year (D16).
    management: ManagementOut
