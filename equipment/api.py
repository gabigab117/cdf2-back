from ninja import Query, Router

from core.schemas import ErrorOut, ValidationErrorOut
from equipment.schemas import AvailabilityOut, AvailabilityQuery
from equipment.services.availability import availability_report
from equipment.services.inventory import ordered_equipment

router = Router(tags=["equipment"])


@router.get(
    "/equipment/availability",
    response={200: AvailabilityOut, 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="Tell what equipment is free over a period",
)
def read_availability(request, period: Query[AvailabilityQuery]):
    """For each equipment: what the loans take of it at their daily peak over
    the period, what remains free, and those loans. The loan being edited is
    left out: its own pieces do not stand in its way.
    """
    return availability_report(ordered_equipment(), period.start, period.end, period.exclude_loan)
