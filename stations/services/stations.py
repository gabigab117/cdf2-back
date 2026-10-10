"""The stations of an event and the volunteers at them (A13).

A station is complete once enough people stand at it, more being allowed. An
event is complete only when each of its stations is: the v1 let one
station's surplus hide another's shortfall.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import BooleanField, Case, Count, F, Max, QuerySet, Sum, Value, When

from events.models import Event
from stations.models import Assignment, Station
from stations.schemas import AssignmentIn, StationIn


@dataclass(frozen=True)
class StationBoard:
    """The stations of an event, in the board's order, and their totals."""

    stations: list[Station]
    required_count: int
    assigned_count: int
    open_places: int
    complete: bool


def event_stations(event: Event) -> QuerySet[Station]:
    """The stations of an event, each with the people at it and whether there
    are enough of them.
    """
    # The order is given again: Django leaves Meta.ordering out of a query that
    # groups its rows, as counting the people does.
    return (
        event.stations.annotate(assigned_count=Count("assignments"))
        .annotate(
            complete=Case(
                When(assigned_count__gte=F("required_count"), then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )
        .prefetch_related("assignments")
        .order_by("sort_order", "name", "pk")
    )


def station_board(event: Event) -> StationBoard:
    """The stations of an event and their totals: the places still to fill are
    counted station by station.
    """
    stations = list(event_stations(event))
    return StationBoard(
        stations=stations,
        required_count=sum(station.required_count for station in stations),
        assigned_count=sum(station.assigned_count for station in stations),
        open_places=sum(
            max(0, station.required_count - station.assigned_count) for station in stations
        ),
        complete=bool(stations) and all(station.complete for station in stations),
    )


def station_totals(event: Event) -> tuple[int, int]:
    """How many people stand at an event's stations, out of how many required."""
    required = event.stations.aggregate(required=Sum("required_count", default=0))["required"]
    return Assignment.objects.filter(station__event=event).count(), required


def create_station(event: Event, data: StationIn) -> Station:
    """Add a station to an event, after its others."""
    last = event.stations.aggregate(last=Max("sort_order"))["last"]
    station = Station(event=event, sort_order=0 if last is None else last + 1)
    return _save(station, data)


def update_station(station: Station, data: StationIn) -> Station:
    """Rewrite a station: its name, description and the people it requires."""
    return _save(station, data)


def delete_station(station: Station) -> None:
    """Delete a station, with the people at it."""
    station.delete()


@transaction.atomic
def reorder_stations(event: Event, order: list[int]) -> StationBoard:
    """Give an event's stations a new order: each of them, once."""
    stations = {station.pk: station for station in event.stations.all()}
    if sorted(order) != sorted(stations):
        raise ValidationError({"stations": "Donnez chaque poste de l’événement, une fois chacun."})
    for position, pk in enumerate(order):
        stations[pk].sort_order = position
    Station.objects.bulk_update(stations.values(), ["sort_order"])
    return station_board(event)


def add_assignment(station: Station, data: AssignmentIn) -> Assignment:
    """Put a volunteer at a station: a name, and a role if any."""
    assignment = Assignment(station=station, name=data.name, role=data.role)
    assignment.full_clean()
    assignment.save()
    return assignment


def remove_assignment(assignment: Assignment) -> None:
    assignment.delete()


def _save(station: Station, data: StationIn) -> Station:
    station.name = data.name
    station.description = data.description
    station.required_count = data.required_count
    station.full_clean()
    station.save()
    # Read again with its people: the answer tells whether it is complete.
    return event_stations(station.event).get(pk=station.pk)
