"""What the board's dashboard shows: a bounded aggregate, never paginated.

The dashboard reads from every app: it sits above them, so that none depends
on another for its figures.
"""

from dataclasses import dataclass

from django.db.models import Count, Q

from documents.models import Document, DocumentStatus
from documents.services.documents import document_counts, listed_documents
from events.models import Event
from events.services.periods import events_in_period
from notes.models import Note
from tasks.models import Task
from tasks.services.tasks import next_tasks, recently_done_tasks, task_counts

# How many events the dashboard's table shows. It sums up: the board's list
# holds them all, and the table leads to it when more are to come.
UPCOMING_EVENTS_COUNT = 5

# How many notes the « Notes du bureau » block shows, every event together.
LATEST_NOTES_COUNT = 3

# The « Tâches générales » block, like the tasks block of an event's page: the
# next tasks, then the last ones done, struck through.
NEXT_GENERAL_TASKS_COUNT = 3
RECENTLY_DONE_GENERAL_TASKS_COUNT = 2

# The « Documents récents » block: the first of the list.
RECENT_DOCUMENTS_COUNT = 4

# The documents to review the « À traiter » panel lists: a bounded aggregate
# (A7), whose count leads to them all.
PENDING_DOCUMENTS_COUNT = 10


@dataclass(frozen=True)
class PendingDocuments:
    """The documents awaiting review: how many, by category, and the latest."""

    counts: dict[str, int]
    items: list[Document]


@dataclass(frozen=True)
class Pending:
    """What awaits the board (A6): the bell's panel and the sidebar's badges.
    The phases 5 to 7 add their own: loans, stock, receipts.
    """

    # Every item awaiting, whatever its kind: the bell shows a dot if any.
    total: int
    documents: PendingDocuments


@dataclass(frozen=True)
class GeneralTasks:
    """The tasks without an event (D10), as their block shows them."""

    tasks_done: int
    tasks_total: int
    next_tasks: list[Task]
    recently_done_tasks: list[Task]


@dataclass(frozen=True)
class BoardOverview:
    """The dashboard's figures. Each phase adds its own."""

    upcoming_events: list[Event]
    upcoming_events_count: int
    latest_notes: list[Note]
    general_tasks: GeneralTasks
    pending: Pending
    recent_documents: list[Document]


def board_overview() -> BoardOverview:
    """The next events, drafts included as in the sidebar, with how far their
    tasks have gone and how many notes they have; how many events are to come;
    the board's latest notes; the general tasks; what awaits the board; and
    the latest documents.
    """
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
        general_tasks=_general_tasks(),
        pending=_pending(),
        recent_documents=list(listed_documents()[:RECENT_DOCUMENTS_COUNT]),
    )


def _pending() -> Pending:
    to_review = listed_documents().filter(status=DocumentStatus.TO_REVIEW)
    counts = document_counts(to_review)
    latest = to_review.order_by("-created_at", "-pk")[:PENDING_DOCUMENTS_COUNT]
    return Pending(
        total=counts["total"],
        documents=PendingDocuments(counts=counts, items=list(latest)),
    )


def _general_tasks() -> GeneralTasks:
    tasks_done, tasks_total = task_counts(None)
    return GeneralTasks(
        tasks_done=tasks_done,
        tasks_total=tasks_total,
        next_tasks=next_tasks(None, NEXT_GENERAL_TASKS_COUNT),
        recently_done_tasks=recently_done_tasks(None, RECENTLY_DONE_GENERAL_TASKS_COUNT),
    )
