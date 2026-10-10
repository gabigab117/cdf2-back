from ninja import Schema

from events.schemas import EventItemOut


class BoardOverviewOut(Schema):
    """What the board's dashboard shows."""

    # The next events, the closest first, drafts included as in the sidebar:
    # the rows of the board's list.
    upcoming_events: list[EventItemOut]
    # How many events are to come in all, those above included.
    upcoming_events_count: int


class EventDashboardOut(Schema):
    """What an event's page shows of its tabs: their counts."""

    # Its notes, replies aside.
    notes_count: int
