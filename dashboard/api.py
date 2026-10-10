from django.shortcuts import get_object_or_404
from ninja import Router

from core.schemas import ErrorOut, ValidationErrorOut
from dashboard.schemas import BoardOverviewOut, EventDashboardOut
from dashboard.services.event_dashboard import event_dashboard
from dashboard.services.overview import board_overview
from events.models import Event

router = Router(tags=["dashboard"])


@router.get(
    "/overview",
    response={200: BoardOverviewOut, 401: ErrorOut, 403: ErrorOut},
    summary="Board overview",
)
def overview(request):
    """The dashboard's figures, whole: a bounded aggregate, never paginated."""
    return board_overview()


@router.get(
    "/events/{event_id}/dashboard",
    response={
        200: EventDashboardOut,
        401: ErrorOut,
        403: ErrorOut,
        404: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Dashboard of an event",
)
def for_event(request, event_id: int):
    """The counts of an event's tabs, whole: a bounded aggregate, never paginated."""
    return event_dashboard(get_object_or_404(Event, pk=event_id))
