"""What the board's dashboard shows: a bounded aggregate, never paginated.

The dashboard reads from every app: it sits above them, so that none depends
on another for its figures.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Count, Q
from django.utils import timezone

from documents.models import Document, DocumentStatus
from documents.services.documents import document_counts, listed_documents
from equipment.models import Loan, LoanState
from equipment.services.board import LoanMovement, loan_movements, next_return, pending_loans
from equipment.services.loans import loan_counts
from events.models import Event
from events.services.periods import events_in_period
from notes.models import Note
from stock.models import StockItem
from stock.services.items import low_items
from tasks.services.tasks import TasksBlock, tasks_block
from treasury.models import LedgerEntry
from treasury.services.entries import missing_receipts
from treasury.services.invoices import unpaid_invoices
from treasury.services.reimbursements import advances_to_reimburse, owed

# How many events the dashboard's table shows. It sums up: the board's list
# holds them all, and the table leads to it when more are to come.
UPCOMING_EVENTS_COUNT = 5

# How many notes the « Notes du bureau » block shows, every event together.
LATEST_NOTES_COUNT = 3


# The « Documents récents » block: the first of the list.
RECENT_DOCUMENTS_COUNT = 4

# How many of each kind of item the « À traiter » panel lists: a bounded
# aggregate (A7), whose count leads to them all. The loans keep their own.
PENDING_COUNT = 10


@dataclass(frozen=True)
class PendingDocuments:
    """The documents awaiting review: how many, by category, and the latest."""

    counts: dict[str, int]
    items: list[Document]


@dataclass(frozen=True)
class PendingLoans:
    """The loans that call for the board: how many are late, how many to
    prepare, and the first of them.
    """

    overdue: int
    to_prepare: int
    items: list[Loan]


@dataclass(frozen=True)
class PendingReceipts:
    """The expenses whose receipt is missing: how many, and the oldest."""

    count: int
    items: list[LedgerEntry]


@dataclass(frozen=True)
class PendingInvoices:
    """The invoices to pay: how many, and the first due."""

    count: int
    items: list[Document]


@dataclass(frozen=True)
class PendingAdvances:
    """The advances the committee owes its members: how many, how much, and
    the oldest.
    """

    count: int
    total: Decimal
    items: list[LedgerEntry]


@dataclass(frozen=True)
class PendingStock:
    """The items of the stock below their threshold: how many, and the first."""

    count: int
    items: list[StockItem]


@dataclass(frozen=True)
class Pending:
    """What awaits the board (A6): the bell's panel and the sidebar's badges."""

    # Every item awaiting, whatever its kind: the bell shows a dot if any.
    total: int
    documents: PendingDocuments
    loans: PendingLoans
    receipts: PendingReceipts
    invoices: PendingInvoices
    advances: PendingAdvances
    stock: PendingStock


@dataclass(frozen=True)
class LoanedEquipment:
    """The KPI « Matériel prêté »: the loans out, late ones included, the
    first due back, and how many are to prepare.
    """

    out_count: int
    to_prepare_count: int
    next_return: Loan | None


@dataclass(frozen=True)
class BoardOverview:
    """The dashboard's figures. Each phase adds its own."""

    upcoming_events: list[Event]
    upcoming_events_count: int
    latest_notes: list[Note]
    general_tasks: TasksBlock
    pending: Pending
    recent_documents: list[Document]
    loans: LoanedEquipment
    loan_movements: list[LoanMovement]


def board_overview() -> BoardOverview:
    """The next events, drafts included as in the sidebar, with how far their
    tasks have gone and how many notes they have; how many events are to come;
    the board's latest notes; the general tasks; what awaits the board; the
    latest documents; and the loans: those out, and the fortnight's checkouts
    and returns.
    """
    today = timezone.localdate()
    by_state = loan_counts(today=today)
    upcoming = events_in_period("upcoming")
    # Counted for the rows shown only. The two counts join two lists: distinct
    # keeps each from multiplying the other.
    rows = upcoming.annotate(
        tasks_total=Count("tasks", distinct=True),
        tasks_done=Count("tasks", filter=Q(tasks__done_at__isnull=False), distinct=True),
        notes_count=Count("notes", distinct=True),
    )
    return BoardOverview(
        upcoming_events=list(rows[:UPCOMING_EVENTS_COUNT]),
        upcoming_events_count=upcoming.count(),
        latest_notes=list(
            Note.objects.filter(parent__isnull=True)
            .select_related("author", "event")
            .order_by("-created_at", "-pk")[:LATEST_NOTES_COUNT]
        ),
        general_tasks=tasks_block(None),
        pending=_pending(by_state, today),
        recent_documents=list(listed_documents()[:RECENT_DOCUMENTS_COUNT]),
        loans=LoanedEquipment(
            out_count=by_state[LoanState.OUT] + by_state[LoanState.OVERDUE],
            to_prepare_count=by_state[LoanState.TO_PREPARE],
            next_return=next_return(today),
        ),
        loan_movements=loan_movements(today),
    )


def _pending(loans_by_state: dict[str, int], today: dt.date) -> Pending:
    to_review = listed_documents().filter(status=DocumentStatus.TO_REVIEW)
    counts = document_counts(to_review)
    latest = to_review.order_by("-created_at", "-pk")[:PENDING_COUNT]
    loans = PendingLoans(
        overdue=loans_by_state[LoanState.OVERDUE],
        to_prepare=loans_by_state[LoanState.TO_PREPARE],
        items=pending_loans(today),
    )
    missing = missing_receipts()
    receipts = PendingReceipts(count=missing.count(), items=list(missing[:PENDING_COUNT]))
    unpaid = unpaid_invoices(today)
    invoices = PendingInvoices(count=unpaid.count(), items=list(unpaid[:PENDING_COUNT]))
    owing = advances_to_reimburse()
    count, total = owed(owing)
    advances = PendingAdvances(count=count, total=total, items=list(owing[:PENDING_COUNT]))
    low = low_items()
    stock = PendingStock(count=low.count(), items=list(low[:PENDING_COUNT]))
    return Pending(
        total=counts["total"]
        + loans.overdue
        + loans.to_prepare
        + receipts.count
        + invoices.count
        + advances.count
        + stock.count,
        documents=PendingDocuments(counts=counts, items=list(latest)),
        loans=loans,
        receipts=receipts,
        invoices=invoices,
        advances=advances,
        stock=stock,
    )
