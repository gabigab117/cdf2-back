import datetime as dt

from ninja import Schema

from accounts.schemas import BoardMemberOut
from events.schemas import EventItemOut
from tasks.schemas import TaskOut


class OverviewEventOut(EventItemOut):
    """An event of the dashboard's table: a row of the board's list, with how
    far its tasks have gone and how many notes it has.
    """

    tasks_done: int
    tasks_total: int
    # Its notes, replies aside.
    notes_count: int


class NoteEventOut(Schema):
    id: int
    title: str


class LatestNoteOut(Schema):
    """A note of the board, as the dashboard lists the latest."""

    id: int
    # None once the author's account is deleted.
    author: BoardMemberOut | None
    text: str
    created_at: dt.datetime
    # None for a general note.
    event: NoteEventOut | None


class GeneralTasksOut(Schema):
    """The tasks without an event (D10), as the dashboard's block shows them."""

    # How many are done, out of how many.
    tasks_done: int
    tasks_total: int
    # The next ones, the one due the soonest first.
    next_tasks: list[TaskOut]
    # Those done last, in the order they were done.
    recently_done_tasks: list[TaskOut]


class BoardOverviewOut(Schema):
    """What the board's dashboard shows."""

    # The next events, the closest first, drafts included as in the sidebar.
    upcoming_events: list[OverviewEventOut]
    # How many events are to come in all, those above included.
    upcoming_events_count: int
    # The board's latest notes, every event together, replies aside.
    latest_notes: list[LatestNoteOut]
    general_tasks: GeneralTasksOut


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
