from django.shortcuts import get_object_or_404
from ninja import Query, Router, Status
from ninja.pagination import paginate

from core.schemas import ErrorOut, ValidationErrorOut
from events.models import Event
from events.schemas import EventFilters, EventIn, EventItemOut, EventOut
from events.services.events import create_event, delete_event, update_event
from events.services.periods import Period, events_in_period

router = Router(tags=["events"])


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
