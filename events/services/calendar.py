"""The calendar files of the public site, in the iCalendar format (RFC 5545)."""

import datetime as dt
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit

from django.utils import timezone
from icalendar import Calendar
from icalendar import Event as CalendarEvent

from events.models import Event

COMMITTEE = "Comité des fêtes d’Ons-en-Bray"
PRODUCT = f"-//{COMMITTEE}//Agenda//FR"
# The address of an event's page on the site.
EVENT_PAGE = "/evenements/{slug}"
# How often a subscribed calendar is asked to fetch the agenda again, at most.
REFRESH_INTERVAL = dt.timedelta(hours=12)


def agenda_calendar(events: Iterable[Event], site: str) -> bytes:
    """The agenda as a calendar feed, which a visitor's calendar subscribes to.

    `site` is the address of the site, such as "https://example.org/": each
    entry links to its event's page.
    """
    calendar = _calendar()
    calendar.calendar_name = COMMITTEE
    calendar.refresh_interval = REFRESH_INTERVAL
    return _with_events(calendar, events, site)


def event_calendar(event: Event, site: str) -> bytes:
    """The calendar file of one event, which a visitor adds to their calendar."""
    return _with_events(_calendar(), [event], site)


def _calendar() -> Calendar:
    # Calendar.new() would give the calendar a random UID on every call.
    calendar = Calendar()
    calendar.prodid = PRODUCT
    calendar.version = "2.0"
    return calendar


def _with_events(calendar: Calendar, events: Iterable[Event], site: str) -> bytes:
    for event in events:
        calendar.add_component(_calendar_event(event, site))
    # The definition of Paris time, which every start and end refers to.
    calendar.add_missing_timezones()
    return calendar.to_ical()


def _calendar_event(event: Event, site: str) -> CalendarEvent:
    page = urljoin(site, EVENT_PAGE.format(slug=event.slug))
    return CalendarEvent.new(
        # The id, unlike the address, never changes: a calendar updates the
        # entry rather than adding another.
        uid=f"event-{event.pk}@{urlsplit(site).hostname}",
        # Without a METHOD, the stamp tells when the event last changed.
        stamp=event.updated_at,
        last_modified=event.updated_at,
        summary=event.title,
        start=timezone.localtime(event.starts_at),
        # An event without an end is shown at its start, no duration made up.
        end=timezone.localtime(event.ends_at) if event.ends_at else None,
        location=", ".join(filter(None, [event.venue_name, event.venue_address])),
        description="\n\n".join(filter(None, [event.summary, page])),
        url=page,
    )
