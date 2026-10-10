"""The figures of an event's page in the board space: the counts its tabs show,
and the block of its tasks.

A bounded aggregate, never paginated (A7). Like the board's overview, it reads
from every app that attaches records to events.
"""

from dataclasses import dataclass

from events.models import Event
from tasks.models import Task
from tasks.services.tasks import next_tasks, recently_done_tasks, task_counts

# The tasks block of the event's page: the next tasks, then the last ones done,
# struck through, as in the mockup.
NEXT_TASKS_COUNT = 3
RECENTLY_DONE_TASKS_COUNT = 2


@dataclass(frozen=True)
class EventDashboard:
    """An event's figures. Each card of phase 3 adds its own."""

    # Its notes, replies aside: a reply has no event of its own.
    notes_count: int
    tasks_done: int
    tasks_total: int
    next_tasks: list[Task]
    recently_done_tasks: list[Task]


def event_dashboard(event: Event) -> EventDashboard:
    """The counts of an event's tabs, and the tasks its block shows."""
    tasks_done, tasks_total = task_counts(event)
    return EventDashboard(
        notes_count=event.notes.count(),
        tasks_done=tasks_done,
        tasks_total=tasks_total,
        next_tasks=next_tasks(event, NEXT_TASKS_COUNT),
        recently_done_tasks=recently_done_tasks(event, RECENTLY_DONE_TASKS_COUNT),
    )
