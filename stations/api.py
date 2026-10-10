from django.shortcuts import get_object_or_404
from ninja import Router, Status

from core.schemas import ErrorOut, ValidationErrorOut
from events.models import Event
from stations.models import Assignment, Station
from stations.schemas import (
    AssignmentIn,
    AssignmentOut,
    StationBoardOut,
    StationIn,
    StationOrderIn,
    StationOut,
)
from stations.services.stations import (
    add_assignment,
    create_station,
    delete_station,
    remove_assignment,
    reorder_stations,
    station_board,
    update_station,
)

router = Router(tags=["stations"])


@router.get(
    "/events/{event_id}/stations",
    response={
        200: StationBoardOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Stations of an event",
)
def board(request, event_id: int):
    """The stations of an event and their totals, whole: a bounded aggregate."""
    return station_board(get_object_or_404(Event, pk=event_id))


@router.post(
    "/events/{event_id}/stations",
    response={
        201: StationOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Add a station to an event",
)
def create(request, event_id: int, payload: StationIn):
    """Add a station after the event's others."""
    return Status(201, create_station(get_object_or_404(Event, pk=event_id), payload))


@router.put(
    "/events/{event_id}/stations/order",
    response={
        200: StationBoardOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Reorder the stations of an event",
)
def reorder(request, event_id: int, payload: StationOrderIn):
    """Give the event's stations a new order: each of them, once."""
    return reorder_stations(get_object_or_404(Event, pk=event_id), payload.stations)


@router.put(
    "/stations/{station_id}",
    response={
        200: StationOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Update a station",
)
def update(request, station_id: int, payload: StationIn):
    return update_station(get_object_or_404(Station, pk=station_id), payload)


@router.delete(
    "/stations/{station_id}",
    response={204: None, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ValidationErrorOut},
    summary="Delete a station",
)
def delete(request, station_id: int):
    """Delete a station, with the people at it."""
    delete_station(get_object_or_404(Station, pk=station_id))
    return Status(204, None)


@router.post(
    "/stations/{station_id}/assignments",
    response={
        201: AssignmentOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Put a volunteer at a station",
)
def assign(request, station_id: int, payload: AssignmentIn):
    return Status(201, add_assignment(get_object_or_404(Station, pk=station_id), payload))


@router.delete(
    "/assignments/{assignment_id}",
    response={204: None, 401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ValidationErrorOut},
    summary="Take a volunteer off a station",
)
def unassign(request, assignment_id: int):
    remove_assignment(get_object_or_404(Assignment, pk=assignment_id))
    return Status(204, None)
