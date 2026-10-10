from django.shortcuts import get_object_or_404
from ninja import Query, Router, Status
from ninja.pagination import paginate

from core.schemas import ErrorOut, ValidationErrorOut
from equipment.models import Equipment, Loan
from equipment.schemas import (
    AvailabilityOut,
    AvailabilityQuery,
    EquipmentIn,
    EquipmentOut,
    InventoryOut,
    LoanCountsOut,
    LoanDepositsOut,
    LoanFilters,
    LoanIn,
    LoanItemOut,
    LoanOut,
    LoanPlanningOut,
    LoanReturnIn,
    LoanReturnOut,
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
from equipment.services.lifecycle import cancel, check_out, reopen, return_loan
from equipment.services.loans import (
    create_loan,
    listed_loans,
    loan_counts,
    loan_deposits,
    loan_planning,
    loans,
    update_loan,
    with_state,
)

router = Router(tags=["equipment"])
loans_router = Router(tags=["loans"])

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


@loans_router.get(
    "/loans",
    response={200: list[LoanItemOut], 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="List the loans",
)
@paginate
def list_loans(request, filters: Query[LoanFilters]):
    """The loans, by page: late, out, to prepare, confirmed, the committee's to
    come, then those over, the latest first. A state keeps its own.
    """
    return filters.filter(listed_loans())


@loans_router.post(
    "/loans",
    response={201: LoanOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="Record a loan",
)
def record_loan(request, payload: LoanIn):
    """Record a loan, never beyond what is free over its days (A15): a loan to
    someone takes the next number of its year.
    """
    return Status(201, create_loan(payload, request.auth))


# Declared before the operations on /loans/{loan_id}: Ninja tries the paths in
# their order, and the id would take "counts", "deposits" or "planning" for itself.
@loans_router.get(
    "/loans/planning",
    response={200: LoanPlanningOut, 401: ErrorOut, 403: ErrorOut},
    summary="Read the planning of the loans",
)
def read_planning(request):
    """The loans over nine weeks, from the Monday of the week before: those of
    the committee and those returned too, the cancelled left out.
    """
    return loan_planning()


@loans_router.get(
    "/loans/counts",
    response={200: LoanCountsOut, 401: ErrorOut, 403: ErrorOut},
    summary="Count the loans by state",
)
def count_loans(request):
    """How many loans in all, and in each state: the counts of the list's chips."""
    return loan_counts()


@loans_router.get(
    "/loans/deposits",
    response={200: LoanDepositsOut, 401: ErrorOut, 403: ErrorOut},
    summary="Read the default deposits",
)
def read_deposits(request):
    """The cheque each type of borrower leaves by default (A16)."""
    return loan_deposits()


@loans_router.get(
    "/loans/{loan_id}",
    response={200: LoanOut, **REFUSALS},
    summary="Read a loan",
)
def read_loan(request, loan_id: int):
    return with_state(get_object_or_404(loans(), pk=loan_id))


@loans_router.put(
    "/loans/{loan_id}",
    response={200: LoanOut, 400: ErrorOut, **REFUSALS},
    summary="Change a loan",
)
def change_loan(request, loan_id: int, payload: LoanIn):
    """Rewrite a loan whole, its lines replaced, never beyond what is free over
    its days, its own pieces left out.
    """
    return update_loan(get_object_or_404(Loan, pk=loan_id), payload)


@loans_router.post(
    "/loans/{loan_id}/checkout",
    response={200: LoanOut, **REFUSALS},
    summary="Hand the equipment of a loan over",
)
def checkout(request, loan_id: int):
    """« Préparer la sortie »: the loan holds its equipment from today, even
    before its start, and is refused if it is not free by then.
    """
    return check_out(get_object_or_404(Loan, pk=loan_id))


@loans_router.post(
    "/loans/{loan_id}/return",
    response={200: LoanReturnOut, 400: ErrorOut, **REFUSALS},
    summary="Record the return of a loan",
)
def record_return(request, loan_id: int, payload: LoanReturnIn):
    """« Valider le retour »: what is damaged goes under repair, what is missing
    is reported. The loans to come that the repairs leave short are named.
    """
    return return_loan(get_object_or_404(Loan, pk=loan_id), payload)


@loans_router.post(
    "/loans/{loan_id}/reopen",
    response={200: LoanOut, **REFUSALS},
    summary="Reopen a returned loan",
)
def reopen_loan(request, loan_id: int):
    """« Rouvrir »: the return is undone, if the equipment is still free."""
    return reopen(get_object_or_404(Loan, pk=loan_id))


@loans_router.post(
    "/loans/{loan_id}/cancel",
    response={200: LoanOut, **REFUSALS},
    summary="Cancel a loan",
)
def cancel_loan(request, loan_id: int):
    return cancel(get_object_or_404(Loan, pk=loan_id))
