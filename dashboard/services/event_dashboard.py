"""The figures of an event's page in the board space: the counts its tabs show.

A bounded aggregate, never paginated (A7). Like the board's overview, it reads
from every app that attaches records to events.
"""

from dataclasses import dataclass

from events.models import Event


@dataclass(frozen=True)
class EventDashboard:
    """An event's figures. Each card of phase 3 adds its own."""

    # Its notes, replies aside: a reply has no event of its own.
    notes_count: int


def event_dashboard(event: Event) -> EventDashboard:
    """The counts of an event's tabs."""
    return EventDashboard(notes_count=event.notes.count())
