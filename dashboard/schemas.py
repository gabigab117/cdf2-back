from ninja import Schema

from events.schemas import EventItemOut
from tasks.schemas import TaskOut


class BoardOverviewOut(Schema):
    """What the board's dashboard shows."""

    # The next events, the closest first, drafts included as in the sidebar:
    # the rows of the board's list.
    upcoming_events: list[EventItemOut]
    # How many events are to come in all, those above included.
    upcoming_events_count: int


class EventDashboardOut(Schema):
    """What an event's page shows of its tabs: their counts, and its tasks block."""

    # Its notes, replies aside.
    notes_count: int
    # How many of its tasks are done, out of how many.
    tasks_done: int
    tasks_total: int
    # Its next tasks, the one due the soonest first.
    next_tasks: list[TaskOut]
    # The tasks done last, in the order they were done.
    recently_done_tasks: list[TaskOut]
    # The people at its stations, out of how many they require.
    assigned_count: int
    required_count: int
    # The places its reservations take, out of its capacity: None for no limit.
    reserved_seats: int
    capacity: int | None
