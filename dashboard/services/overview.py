"""What the board's dashboard shows: a bounded aggregate, never paginated.

The dashboard reads from every app: it sits above them, so that none depends
on another for its figures.
"""

from dataclasses import dataclass

from events.models import Event
from events.services.periods import events_in_period

# How many events the dashboard's table shows. It sums up: the board's list
# holds them all, and the table leads to it when more are to come.
UPCOMING_EVENTS_COUNT = 5


@dataclass(frozen=True)
class BoardOverview:
    """The dashboard's figures. Each phase adds its own."""

    upcoming_events: list[Event]
    upcoming_events_count: int


def board_overview() -> BoardOverview:
    """The next events, drafts included as in the sidebar, and how many are to come."""
    upcoming = events_in_period("upcoming")
    return BoardOverview(
        upcoming_events=list(upcoming[:UPCOMING_EVENTS_COUNT]),
        upcoming_events_count=upcoming.count(),
    )
