from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.http import content_disposition_header
from ninja import Query, Router, Status
from ninja.pagination import paginate

from core.schemas import ErrorOut, ValidationErrorOut
from events.models import Event
from events.schemas import (
    AgendaOut,
    EventFilters,
    EventIn,
    EventItemOut,
    EventOut,
    PublicEventFilters,
    PublicEventItemOut,
    PublicEventOut,
)
from events.services.agenda import (
    agenda,
    agenda_categories,
    agenda_updated_at,
    next_events,
    published_events,
)
from events.services.calendar import agenda_calendar, event_calendar
from events.services.events import create_event, delete_event, update_event
from events.services.periods import Period, events_in_period

router = Router(tags=["events"])

# The public site's operations: open to anyone, read-only, each declaring
# auth=None. No throttle: the server rendering of the site calls them all from
# a single address, and would be throttled for every visitor at once.
public_router = Router(tags=["site"])

# A calendar file is not JSON: the operation returns it as it is, and declares
# its content here.
CALENDAR_FILE = {
    "responses": {
        200: {
            "description": "iCalendar file",
            "content": {"text/calendar": {"schema": {"type": "string"}}},
        }
    }
}


@router.get(
    "/events",
    response={200: list[EventItemOut], 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="List the events",
)
@paginate
def list_events(request, filters: Query[EventFilters], period: Period | None = None):
    """The events of the board, by page.

    Upcoming events come the next first; past ones, like the whole list, the
    latest first. An event stays upcoming until the end of its last day.
    """
    return filters.filter(events_in_period(period))


@router.post(
    "/events",
    response={
        201: EventOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Create an event",
)
def create(request, payload: EventIn):
    """Record an event, with its programme and practical info."""
    return Status(201, create_event(payload))


@router.get(
    "/events/{event_id}",
    response={
        200: EventOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Get an event",
)
def detail(request, event_id: int):
    """An event with all its content."""
    return get_object_or_404(
        Event.objects.select_related("lead", "previous_edition").prefetch_related(
            "programme", "practical_infos"
        ),
        pk=event_id,
    )


@router.put(
    "/events/{event_id}",
    response={
        200: EventOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Update an event",
)
def update(request, event_id: int, payload: EventIn):
    """Rewrite an event whole: its programme and practical info are replaced."""
    # Read without prefetching its lines: the answer shows the ones just written.
    return update_event(get_object_or_404(Event, pk=event_id), payload)


@router.delete(
    "/events/{event_id}",
    response={204: None, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ValidationErrorOut},
    summary="Delete an event",
)
def delete(request, event_id: int):
    """Delete an event, with its programme and practical info."""
    delete_event(get_object_or_404(Event, pk=event_id))
    return Status(204, None)


def _calendar_file(content: bytes, filename: str) -> HttpResponse:
    return HttpResponse(
        content,
        content_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": content_disposition_header(True, filename)},
    )


def _site(request) -> str:
    # A calendar file is fetched by the visitor's browser or calendar, through
    # the site's public address, never by the server rendering: the address of
    # the request is the site's.
    return request.build_absolute_uri("/")


@public_router.get(
    "/events",
    auth=None,
    response={200: list[PublicEventItemOut], 422: ValidationErrorOut},
    summary="List the agenda",
)
@paginate
def list_agenda(request, filters: Query[PublicEventFilters]):
    """The published events to come, the next first, by page."""
    return filters.filter(agenda())


@public_router.get(
    "/agenda",
    auth=None,
    response={200: AgendaOut},
    summary="Agenda overview",
)
def agenda_overview(request):
    """The categories of the agenda's events, and when the board last changed one."""
    return {"categories": agenda_categories(), "updated_at": agenda_updated_at()}


@public_router.get(
    "/agenda.ics",
    auth=None,
    response={200: None},
    openapi_extra=CALENDAR_FILE,
    summary="Calendar feed of the agenda",
)
def agenda_feed(request):
    """Every published event, past ones included: a subscribed calendar keeps them."""
    return _calendar_file(agenda_calendar(published_events(), _site(request)), "agenda.ics")


# Declared before /events/{slug}: the routes are tried in order, and that one
# would take "halloween-2026.ics" for the address of an event.
@public_router.get(
    "/events/{slug}.ics",
    auth=None,
    response={200: None, 404: ErrorOut},
    openapi_extra=CALENDAR_FILE,
    summary="Calendar file of an event",
)
def event_file(request, slug: str):
    """A published event, to add to one's calendar."""
    event = get_object_or_404(published_events(), slug=slug)
    return _calendar_file(event_calendar(event, _site(request)), f"{event.slug}.ics")


@public_router.get(
    "/events/{slug}",
    auth=None,
    response={200: PublicEventOut, 404: ErrorOut},
    summary="Get a published event",
)
def public_event(request, slug: str):
    """A published event's page, past ones included, with the events that follow it."""
    event = get_object_or_404(
        published_events().prefetch_related("programme", "practical_infos"), slug=slug
    )
    event.next_events = next_events(event)
    return event
