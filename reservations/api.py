from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.http import content_disposition_header
from ninja import Router, Status
from ninja.pagination import paginate

from core.schemas import ErrorOut, ValidationErrorOut
from events.models import Event
from reservations.models import Reservation, TicketType
from reservations.schemas import (
    CapacityIn,
    ReservationIn,
    ReservationOut,
    ReservationStatsOut,
    TicketTypeIn,
    TicketTypeOut,
)
from reservations.services.reservations import (
    create_reservation,
    create_ticket_type,
    delete_reservation,
    delete_ticket_type,
    event_reservations,
    reservation_stats,
    set_capacity,
    update_reservation,
)
from reservations.services.workbook import XLSX, reservations_workbook

router = Router(tags=["reservations"])

# A workbook is not JSON: the operation returns it as it is, and declares its
# content here.
XLSX_FILE = {
    "responses": {
        200: {
            "description": "Excel workbook",
            "content": {XLSX: {"schema": {"type": "string", "format": "binary"}}},
        }
    }
}

# What every operation on an existing object may answer besides its success.
REFUSALS = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ValidationErrorOut}


@router.get(
    "/events/{event_id}/reservations",
    response={200: list[ReservationOut], **REFUSALS},
    summary="List the reservations of an event",
)
@paginate
def list_reservations(request, event_id: int):
    """The reservations of an event, by page, the latest first."""
    return event_reservations(get_object_or_404(Event, pk=event_id))


@router.post(
    "/events/{event_id}/reservations",
    response={201: ReservationOut, 400: ErrorOut, **REFUSALS},
    summary="Record a reservation",
)
def create(request, event_id: int, payload: ReservationIn):
    """Record a reservation, within the event's capacity."""
    return Status(201, create_reservation(get_object_or_404(Event, pk=event_id), payload))


@router.get(
    "/events/{event_id}/reservations/stats",
    response={200: ReservationStatsOut, **REFUSALS},
    summary="Figures of the reservations of an event",
)
def stats(request, event_id: int):
    """The reservations, places taken and still free, and the places by type, whole."""
    return reservation_stats(get_object_or_404(Event, pk=event_id))


@router.get(
    "/events/{event_id}/reservations.xlsx",
    response={200: None, **REFUSALS},
    openapi_extra=XLSX_FILE,
    summary="Export the reservations of an event",
)
def export(request, event_id: int):
    """The reservations as an Excel workbook, in the v1's format."""
    event = get_object_or_404(Event, pk=event_id)
    return HttpResponse(
        reservations_workbook(event),
        content_type=XLSX,
        headers={
            "Content-Disposition": content_disposition_header(
                True, f"reservations-{event.slug}.xlsx"
            )
        },
    )


@router.put(
    "/events/{event_id}/capacity",
    response={200: ReservationStatsOut, 400: ErrorOut, **REFUSALS},
    summary="Set the capacity of an event",
)
def capacity(request, event_id: int, payload: CapacityIn):
    """Set how many places the reservations may take, or no limit: the figures follow."""
    return set_capacity(get_object_or_404(Event, pk=event_id), payload.capacity)


@router.post(
    "/events/{event_id}/ticket-types",
    response={201: TicketTypeOut, 400: ErrorOut, **REFUSALS},
    summary="Add a type of place to an event",
)
def create_type(request, event_id: int, payload: TicketTypeIn):
    return Status(201, create_ticket_type(get_object_or_404(Event, pk=event_id), payload))


@router.delete(
    "/ticket-types/{ticket_type_id}",
    response={204: None, **REFUSALS},
    summary="Delete a type of place",
)
def delete_type(request, ticket_type_id: int):
    """Delete a type of place no reservation uses: one in use is refused (422)."""
    delete_ticket_type(get_object_or_404(TicketType, pk=ticket_type_id))
    return Status(204, None)


@router.put(
    "/reservations/{reservation_id}",
    response={200: ReservationOut, 400: ErrorOut, **REFUSALS},
    summary="Update a reservation",
)
def update(request, reservation_id: int, payload: ReservationIn):
    """Rewrite a reservation, its places replaced: only an increase meets the capacity."""
    return update_reservation(get_object_or_404(Reservation, pk=reservation_id), payload)


@router.delete(
    "/reservations/{reservation_id}",
    response={204: None, **REFUSALS},
    summary="Delete a reservation",
)
def delete(request, reservation_id: int):
    delete_reservation(get_object_or_404(Reservation, pk=reservation_id))
    return Status(204, None)
