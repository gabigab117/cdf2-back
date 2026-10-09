"""The events the public site shows: those the board has published."""

import datetime as dt

from django.db.models import Max, Q, QuerySet

from events.models import Event, EventCategory
from events.services.periods import events_in_period

# How many events an event's page suggests next, under "Ensuite au programme".
NEXT_EVENTS_COUNT = 2


def published_events() -> QuerySet[Event]:
    """Every published event, past ones included, the oldest first."""
    return Event.objects.filter(published=True).order_by("starts_at", "pk")


def agenda() -> QuerySet[Event]:
    """The agenda of the site: the published events to come, the next first."""
    return events_in_period("upcoming").filter(published=True)


def agenda_categories() -> list[EventCategory]:
    """The categories of the agenda's events, in their usual order.

    The site's filter offers those only.
    """
    present = set(agenda().values_list("category", flat=True))
    return [category for category in EventCategory if category.value in present]


def agenda_updated_at() -> dt.datetime | None:
    """When the board last changed an event of the agenda, if it holds any.

    Deleting or unpublishing an event leaves no trace: the date stays.
    """
    return agenda().aggregate(updated_at=Max("updated_at"))["updated_at"]


def next_events(event: Event) -> list[Event]:
    """The events that come after an event on the agenda.

    A past event is followed by the first events of the agenda, and the last
    event of the agenda by none.
    """
    # Event.get_next_by_starts_at() gives a single event and cannot be held to
    # the agenda: its comparison, on the start then the id, is written here.
    after = Q(starts_at__gt=event.starts_at) | Q(starts_at=event.starts_at, pk__gt=event.pk)
    return list(agenda().filter(after)[:NEXT_EVENTS_COUNT])
