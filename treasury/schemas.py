import datetime as dt
from decimal import Decimal
from typing import Annotated

from django.db.models import Q
from ninja import Field, FilterLookup, FilterSchema, Schema

from accounts.schemas import BoardMemberOut
from core.schemas import InputSchema
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
