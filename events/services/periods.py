"""The periods of the events, upcoming or past, seen from today in Paris."""

import datetime as dt
from typing import Literal

from django.db.models import Q, QuerySet
from django.utils import timezone

from events.models import Event

Period = Literal["upcoming", "past"]


def events_in_period(period: Period | None) -> QuerySet[Event]:
    """The events of a period, or all of them.

    An event stays upcoming until the end of its last day: until its end, or
    its start when it has none, falls before today. Upcoming events come the
    next first; past ones, like the whole list, the latest first.
    """
    not_over = _not_over_on(timezone.localdate())
    if period == "upcoming":
        return Event.objects.filter(not_over).order_by("starts_at", "pk")
    events = Event.objects.order_by("-starts_at", "-pk")
    return events.exclude(not_over) if period == "past" else events


def _not_over_on(day: dt.date) -> Q:
    start_of_day = timezone.make_aware(dt.datetime.combine(day, dt.time.min))
    return Q(ends_at__gte=start_of_day) | Q(ends_at__isnull=True, starts_at__gte=start_of_day)
