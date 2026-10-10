"""The loans of equipment (A14, A16), written under locks and never beyond what
is free (A15).

A write locks the loan first, then the equipment of its old and new lines, in
the order of their keys: two writes never wait on each other in a circle, and
what the write reads as free cannot change before it writes. A loan to someone
takes its number from the counter of its year, locked last.
"""

import datetime as dt
from decimal import Decimal

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db import transaction
from django.db.models import Prefetch, QuerySet
from django.utils import timezone
from django.utils.translation import ngettext

from accounts.models import User
from equipment.models import (
    Equipment,
    Loan,
    LoanBorrowerType,
    LoanLine,
    LoanNumberSequence,
    LoanStatus,
)
from equipment.schemas import LoanIn
from equipment.services.availability import availability
from equipment.services.states import loan_state

# The cheque a borrower leaves by default, by type (A16): the committee leaves none.
DEFAULT_DEPOSITS = {
    LoanBorrowerType.ASSOCIATION: Decimal("150.00"),
    LoanBorrowerType.INDIVIDUAL: Decimal("300.00"),
    LoanBorrowerType.MUNICIPALITY: Decimal("0.00"),
    LoanBorrowerType.COMMITTEE: Decimal("0.00"),
}

# The statuses a loan is still written in: a returned loan is reopened first.
WRITABLE = {LoanStatus.CONFIRMED, LoanStatus.OUT}


def loans() -> QuerySet[Loan]:
    """The loans, with what their page shows: their event, author, and lines
    with their equipment.
    """
    lines = LoanLine.objects.select_related("equipment").order_by("equipment__name", "pk")
    return Loan.objects.select_related("event", "created_by").prefetch_related(
        Prefetch("lines", queryset=lines)
    )


def with_state(loan: Loan, *, today: dt.date | None = None) -> Loan:
    """A loan read alone, with its state of today, as a list annotates it."""
    loan.state = loan_state(loan, today or timezone.localdate())
    return loan


def loan_deposits() -> dict[str, list[dict[str, object]]]:
    """The default deposit of each type of borrower, in the order of the form."""
    return {
        "deposits": [
            {"borrower_type": kind, "amount": amount} for kind, amount in DEFAULT_DEPOSITS.items()
        ]
    }


@transaction.atomic
def create_loan(data: LoanIn, author: User) -> Loan:
    """Record a loan, numbered if it lends to someone."""
    loan = Loan(created_by=author)
    return _write(loan, data)


@transaction.atomic
def update_loan(loan: Loan, data: LoanIn) -> Loan:
    """Rewrite a loan whole, its lines replaced: confirmed, out to extend a
    late return, or kept by the committee.
    """
    loan = Loan.objects.select_for_update().get(pk=loan.pk)
    if loan.status == LoanStatus.RETURNED:
        raise ValidationError("Ce prêt est rendu : rouvrez-le avant de le modifier.")
    if loan.status == LoanStatus.CANCELLED:
        raise ValidationError("Ce prêt est annulé : il ne se modifie plus.")
    committee = LoanBorrowerType.COMMITTEE
    if (loan.borrower_type == committee) != (data.borrower_type == committee):
        raise ValidationError(
            {"borrower_type": "Un usage comité ne devient pas un prêt à un tiers, ni l’inverse."}
        )
    return _write(loan, data)


def _write(loan: Loan, data: LoanIn) -> Loan:
    committee = data.borrower_type == LoanBorrowerType.COMMITTEE
    loan.borrower_type = data.borrower_type
    # A committee loan keeps its equipment for an event: no borrower, no deposit.
    loan.borrower_name = "" if committee else data.borrower_name
    loan.purpose = "" if committee else data.purpose
    loan.phone = "" if committee else data.phone
    loan.event_id = data.event if committee else None
    loan.start_date = data.start_date
    loan.end_date = data.end_date
    loan.deposit_amount = (
        DEFAULT_DEPOSITS[data.borrower_type]
        if committee or data.deposit_amount is None
        else data.deposit_amount
    )
    loan.notes = data.notes
    lines = [
        LoanLine(loan=loan, equipment_id=line.equipment, quantity=line.quantity)
        for line in data.lines
    ]
    previous = set(loan.lines.values_list("equipment_id", flat=True)) if loan.pk else set()
    locked = _lock({line.equipment_id for line in lines} | previous)
    _validate(loan, lines)
    _check_free(loan, lines, locked)
    if loan.number is None and not committee:
        loan.number = _next_number()
    loan.save()
    loan.lines.all().delete()
    LoanLine.objects.bulk_create(lines)
    return with_state(loans().get(pk=loan.pk))


def _lock(ids: set[int]) -> dict[int, Equipment]:
    """Lock the equipment a write touches, in the order of their keys."""
    equipment = Equipment.objects.select_for_update().filter(pk__in=ids).order_by("pk")
    return {item.pk: item for item in equipment}


def _validate(loan: Loan, lines: list[LoanLine]) -> None:
    """Check the loan and each of its lines before anything is written, every
    error at once, a line's under its position: "lines.1.quantity".
    """
    errors: dict[str, list[str]] = {}
    try:
        # The number is given once the loan is valid.
        loan.full_clean(exclude={"number"})
    except ValidationError as error:
        errors |= error.message_dict
    seen: set[int] = set()
    for index, line in enumerate(lines):
        # The loan may not be recorded yet: its unique constraint with the
        # equipment is checked below, among the lines of the request.
        try:
            line.full_clean(exclude={"loan"})
        except ValidationError as error:
            for field, messages in error.message_dict.items():
                errors[f"lines.{index}.{field}"] = messages
        if line.equipment_id in seen:
            errors.setdefault(f"lines.{index}.equipment", []).append(
                "Ce matériel figure déjà dans le prêt."
            )
        seen.add(line.equipment_id)
    if not lines:
        errors[NON_FIELD_ERRORS] = ["Ajoutez au moins un matériel."]
    if errors:
        raise ValidationError(errors)


def _check_free(loan: Loan, lines: list[LoanLine], locked: dict[int, Equipment]) -> None:
    """Refuse a line beyond what is free over the loan's days, itself left out:
    from the day it left, and until today if it is out (A15).
    """
    start, end = loan.start_date, loan.end_date
    if loan.status == LoanStatus.OUT:
        today = timezone.localdate()
        start, end = min(start, today), max(end, today)
    asked = [locked[line.equipment_id] for line in lines]
    free = {
        item.equipment.pk: item.free
        for item in availability(asked, start, end, exclude_loan=loan.pk)
    }
    errors = {}
    for index, line in enumerate(lines):
        if line.quantity > free[line.equipment_id]:
            errors[f"lines.{index}.quantity"] = _beyond(
                locked[line.equipment_id], line.quantity, free[line.equipment_id]
            )
    if errors:
        raise ValidationError(errors)


def _beyond(equipment: Equipment, asked: int, free: int) -> str:
    """« Barnums 3 × 3 m : 2 demandés, 1 libre sur la période. »"""
    demanded = ngettext("%(count)d demandé", "%(count)d demandés", asked) % {"count": asked}
    left = ngettext("%(count)d libre", "%(count)d libres", free) % {"count": free}
    return f"{equipment.name} : {demanded}, {left} sur la période."


def _next_number() -> str:
    """The next number of the year, P-2026-018: its counter stays locked until the
    loan is written.
    """
    year = timezone.localdate().year
    sequence, _created = LoanNumberSequence.objects.select_for_update().get_or_create(year=year)
    sequence.last_number += 1
    sequence.save(update_fields=["last_number"])
    return f"P-{year}-{sequence.last_number:03}"
