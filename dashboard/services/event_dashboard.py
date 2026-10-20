"""The figures of an event's page in the board space: the counts its tabs show,
and the block of its tasks.

A bounded aggregate, never paginated (A7). Like the board's overview, it reads
from every app that attaches records to events.
"""

from dataclasses import dataclass

from django.utils import timezone

from documents.models import Document
from documents.services.documents import listed_documents
from equipment.models import Loan
from equipment.services.board import event_committee_loan
from events.models import Event
from reservations.services.reservations import reserved_seats
from stations.services.stations import station_totals
from tasks.models import Task
from tasks.services.tasks import tasks_block

# The « Documents liés » block beside the notes: the latest, then a link to the
# documents' tab.
RELATED_DOCUMENTS_COUNT = 5


@dataclass(frozen=True)
class EventDashboard:
    """An event's figures: the counts of its tabs, its tasks block, its
    reservations, its documents and the equipment it keeps.
    """

    # Its notes, replies aside: a reply has no event of its own.
    notes_count: int
    tasks_done: int
    tasks_total: int
    next_tasks: list[Task]
    recently_done_tasks: list[Task]
    # The people at its stations, out of how many they require.
    assigned_count: int
    required_count: int
    # The places its reservations take, out of its capacity, if any.
    reserved_seats: int
    capacity: int | None
    documents_count: int
    # Its latest documents, in the order of the list.
    documents: list[Document]
    # The lines of the equipment it keeps, and its committee loan, if any.
    equipment_count: int
    committee_loan: Loan | None


def event_dashboard(event: Event) -> EventDashboard:
    """The counts of an event's tabs, the tasks its block shows, and the
    equipment it keeps.
    """
    tasks = tasks_block(event.pk)
    assigned_count, required_count = station_totals(event)
    committee_loan = event_committee_loan(event, timezone.localdate())
    return EventDashboard(
        notes_count=event.notes.count(),
        tasks_done=tasks.tasks_done,
        tasks_total=tasks.tasks_total,
        next_tasks=tasks.next_tasks,
        recently_done_tasks=tasks.recently_done_tasks,
        assigned_count=assigned_count,
        required_count=required_count,
        reserved_seats=reserved_seats(event),
        capacity=event.capacity,
        documents_count=event.documents.count(),
        documents=list(listed_documents().filter(event=event)[:RELATED_DOCUMENTS_COUNT]),
        equipment_count=len(committee_loan.lines.all()) if committee_loan else 0,
        committee_loan=committee_loan,
    )
