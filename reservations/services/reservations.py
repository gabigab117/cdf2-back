"""The reservations the board records for an event (D1): places by type,
within the event's capacity.

Each write locks the event first (select_for_update): two reservations
recorded at once cannot both take the last places.
"""

from dataclasses import dataclass

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.db.models import Count, Max, QuerySet, RestrictedError, Sum
from django.utils.translation import ngettext

from events.models import Event
from reservations.models import Reservation, ReservationLine, TicketType
from reservations.schemas import ReservationIn, TicketTypeIn


@dataclass(frozen=True)
class ReservationStats:
    """The figures of an event's reservations."""

    capacity: int | None
    reservations: int
    seats: int
    remaining: int | None
    ticket_types: list[TicketType]


def event_reservations(event: Event) -> QuerySet[Reservation]:
    """The reservations of an event, the latest first, with their places."""
    # The order is given again: Django leaves Meta.ordering out of a query that
    # groups its rows, as summing the places does.
    return (
        event.reservations.annotate(seats=Sum("lines__quantity", default=0))
        .prefetch_related("lines")
        .order_by("-created_at", "-pk")
    )


def reservation_stats(event: Event) -> ReservationStats:
    """The reservations of an event, its places by type, and those still free."""
    ticket_types = list(
        event.ticket_types.annotate(
            seats=Sum("lines__quantity", default=0), reservations=Count("lines")
        ).order_by("sort_order", "name", "pk")
    )
    seats = sum(ticket_type.seats for ticket_type in ticket_types)
    return ReservationStats(
        capacity=event.capacity,
        reservations=event.reservations.count(),
        seats=seats,
        remaining=None if event.capacity is None else max(event.capacity - seats, 0),
        ticket_types=ticket_types,
    )


def reserved_seats(event: Event) -> int:
    """How many places the reservations of an event take."""
    lines = ReservationLine.objects.filter(reservation__event=event)
    return lines.aggregate(seats=Sum("quantity", default=0))["seats"]


@transaction.atomic
def create_reservation(event: Event, data: ReservationIn) -> Reservation:
    """Record a reservation, within the event's capacity."""
    event = Event.objects.select_for_update().get(pk=event.pk)
    reservation = Reservation(event=event)
    return _save(reservation, data, event, current=0)


@transaction.atomic
def update_reservation(reservation: Reservation, data: ReservationIn) -> Reservation:
    """Rewrite a reservation, its lines replaced. Only an increase of its
    places is checked against the capacity, as in the v1.
    """
    event = Event.objects.select_for_update().get(pk=reservation.event_id)
    current = reservation.lines.aggregate(seats=Sum("quantity", default=0))["seats"]
    return _save(reservation, data, event, current)


def delete_reservation(reservation: Reservation) -> None:
    reservation.delete()


def create_ticket_type(event: Event, data: TicketTypeIn) -> TicketType:
    """Add a type of place to an event, after its others."""
    last = event.ticket_types.aggregate(last=Max("sort_order"))["last"]
    ticket_type = TicketType(
        event=event, name=data.name, sort_order=0 if last is None else last + 1
    )
    ticket_type.full_clean()
    ticket_type.save()
    return ticket_type


def delete_ticket_type(ticket_type: TicketType) -> None:
    """Delete a type of place no reservation uses."""
    # RESTRICT refuses it before any query: the transaction stays usable.
    try:
        ticket_type.delete()
    except RestrictedError as error:
        raise ValidationError(
            f"Impossible de supprimer « {ticket_type.name} » : des réservations l’utilisent."
        ) from error


def set_capacity(event: Event, capacity: int | None) -> ReservationStats:
    """Set how many places the reservations of an event may take, or no limit."""
    event.capacity = capacity
    # Only the capacity is checked: the event's other values are not the
    # reservations' to judge, such as a lead who has left the board since.
    event.clean_fields(exclude={field.name for field in Event._meta.fields} - {"capacity"})
    # The date of the event's last change stays: the public agenda shows it.
    event.save(update_fields=["capacity"])
    return reservation_stats(event)


def _save(reservation: Reservation, data: ReservationIn, event: Event, current: int) -> Reservation:
    reservation.name = data.name
    reservation.note = data.note
    lines = [
        ReservationLine(
            reservation=reservation, ticket_type_id=line.ticket_type, quantity=line.quantity
        )
        for line in data.lines
    ]
    _validate(reservation, lines)
    _check_capacity(event, sum(line.quantity for line in lines), current)
    reservation.save()
    reservation.lines.all().delete()
    ReservationLine.objects.bulk_create(lines)
    return event_reservations(event).get(pk=reservation.pk)


def _validate(reservation: Reservation, lines: list[ReservationLine]) -> None:
    """Check the reservation and each of its lines before anything is written,
    every error at once, a line's under its position: "lines.1.quantity".
    """
    errors: dict[str, list[str]] = {}
    try:
        reservation.full_clean()
    except ValidationError as error:
        errors |= error.message_dict
    seen: set[int] = set()
    for index, line in enumerate(lines):
        # The reservation may not be recorded yet: its unique constraint with
        # the type is checked below, among the lines of the request.
        try:
            line.full_clean(exclude={"reservation"})
        except ValidationError as error:
            for field, messages in error.message_dict.items():
                errors[f"lines.{index}.{field}"] = messages
        if line.ticket_type_id in seen:
            errors.setdefault(f"lines.{index}.ticket_type", []).append(
                "Ce type de place figure déjà dans la réservation."
            )
        seen.add(line.ticket_type_id)
    if not lines:
        errors[NON_FIELD_ERRORS] = ["Indiquez au moins une place."]
    if errors:
        raise ValidationError(errors)


def _check_capacity(event: Event, requested: int, current: int) -> None:
    """Refuse places beyond the capacity. Only an increase is checked: a
    reservation that keeps or lowers its places passes, even on an event
    already over its capacity.
    """
    if event.capacity is None or requested <= current:
        return
    remaining = event.capacity - reserved_seats(event)
    if requested - current <= remaining:
        return
    if remaining <= 0:
        raise ValidationError(f"Complet : les {event.capacity} places sont déjà réservées.")
    raise ValidationError(
        ngettext(
            "Capacité dépassée : il ne reste que %(remaining)d place sur %(capacity)d.",
            "Capacité dépassée : il ne reste que %(remaining)d places sur %(capacity)d.",
            remaining,
        )
        % {"remaining": remaining, "capacity": event.capacity}
    )
