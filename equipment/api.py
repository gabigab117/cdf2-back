from django.shortcuts import get_object_or_404
from ninja import Query, Router, Status

from core.schemas import ErrorOut, ValidationErrorOut
from equipment.models import Equipment
from equipment.schemas import (
    AvailabilityOut,
    AvailabilityQuery,
    EquipmentIn,
    EquipmentOut,
    InventoryOut,
    OccupancyOut,
)
from equipment.services.availability import availability_report
from equipment.services.inventory import (
    create_equipment,
    delete_equipment,
    inventory,
    occupancy,
    ordered_equipment,
    update_equipment,
)

router = Router(tags=["equipment"])

# What every operation on an existing equipment may answer besides its success.
REFUSALS = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ValidationErrorOut}


@router.get(
    "/equipment",
    response={200: InventoryOut, 401: ErrorOut, 403: ErrorOut},
    summary="Read today's inventory",
)
def read_inventory(request):
    """What each equipment offers today, by category: its pieces, those taken
    today and those under repair, with the figures of the inventory.
    """
    return inventory()


@router.post(
    "/equipment",
    response={
        201: EquipmentOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Add equipment",
)
def create(request, payload: EquipmentIn):
    return Status(201, create_equipment(payload))


# Declared before the operations on /equipment/{equipment_id}: Ninja tries the
# paths in their order, and the id would take "availability" for itself.
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


@router.put(
    "/equipment/{equipment_id}",
    response={200: EquipmentOut, 400: ErrorOut, **REFUSALS},
    summary="Change equipment",
)
def update(request, equipment_id: int, payload: EquipmentIn):
    """Rewrite an equipment whole, such as the pieces put back in service.

    Fewer pieces offered are refused if a loan to come would then lack some.
    """
    return update_equipment(get_object_or_404(Equipment, pk=equipment_id), payload)


@router.delete(
    "/equipment/{equipment_id}",
    response={204: None, **REFUSALS},
    summary="Delete equipment",
)
def delete(request, equipment_id: int):
    """Delete an equipment no loan names."""
    delete_equipment(get_object_or_404(Equipment, pk=equipment_id))
    return Status(204, None)


@router.get(
    "/equipment/{equipment_id}/occupancy",
    response={200: OccupancyOut, **REFUSALS},
    summary="Read the occupancy of equipment",
)
def read_occupancy(request, equipment_id: int):
    """The loans that take an equipment, from the Monday of this week, for
    eleven weeks.
    """
    return occupancy(get_object_or_404(Equipment, pk=equipment_id))
