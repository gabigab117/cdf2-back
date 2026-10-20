"""The committee's equipment, as the inventory lists and writes it.

An equipment written locks its row first (select_for_update), as a loan's
writes do: a change of its pieces cannot slip between a loan's reading of what
is free and its writing.
"""

import datetime as dt
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import ProtectedError
from django.utils import timezone

from core.text import counted
from equipment.models import Equipment, Loan
from equipment.schemas import EquipmentIn
from equipment.services.availability import Availability, Conflict, availability, shortages

# The occupancy of an equipment, beside the inventory: from the Monday of this
# week, for eleven weeks.
OCCUPANCY_WEEKS = 11


@dataclass(frozen=True)
class InventoryTotals:
    """The figures under the inventory's title."""

    references: int
    # The equipment some pieces of which are taken today.
    taken_today: int
    pieces_under_repair: int


@dataclass(frozen=True)
class Inventory:
    """Today's inventory: what each equipment offers today, by name, and its
    figures. A bounded aggregate (A7).
    """

    day: dt.date
    items: list[Availability]
    totals: InventoryTotals


@dataclass(frozen=True)
class Occupancy:
    """The loans that take an equipment over the weeks to come."""

    start: dt.date
    end: dt.date
    loans: list[Conflict]


def inventory(*, today: dt.date | None = None) -> Inventory:
    """What each equipment offers today, with the figures of the inventory."""
    today = today or timezone.localdate()
    items = availability(Equipment.objects.all(), today, today, today=today)
    return Inventory(
        day=today,
        items=items,
        totals=InventoryTotals(
            references=len(items),
            taken_today=sum(1 for item in items if item.taken),
            pieces_under_repair=sum(item.equipment.repair_quantity for item in items),
        ),
    )


def occupancy(equipment: Equipment) -> Occupancy:
    """The loans that take an equipment, from the Monday of this week, for
    eleven weeks.
    """
    today = timezone.localdate()
    start = today - dt.timedelta(days=today.weekday())
    end = start + dt.timedelta(weeks=OCCUPANCY_WEEKS, days=-1)
    [item] = availability([equipment], start, end, today=today)
    return Occupancy(start, end, item.conflicts)


def create_equipment(data: EquipmentIn) -> Equipment:
    """Add an equipment to the inventory."""
    equipment = Equipment()
    _write(equipment, data)
    equipment.full_clean()
    equipment.save()
    return equipment


@transaction.atomic
def update_equipment(equipment: Equipment, data: EquipmentIn) -> Equipment:
    """Rewrite an equipment whole. Fewer pieces offered, by more under repair or
    a lower total, are refused if a loan to come would then lack some (A17).
    """
    equipment = Equipment.objects.select_for_update().get(pk=equipment.pk)
    offered = equipment.offered
    repair = equipment.repair_quantity
    _write(equipment, data)
    equipment.full_clean()
    if equipment.offered < offered:
        _check_shortage(equipment, repair)
    equipment.save()
    return equipment


def delete_equipment(equipment: Equipment) -> None:
    """Delete an equipment no loan names: the loans keep their history."""
    # PROTECT refuses it before any deletion: the transaction stays usable.
    try:
        equipment.delete()
    except ProtectedError as error:
        loans = counted(len(error.protected_objects), "prêt", "prêts")
        raise ValidationError(
            f"Impossible de supprimer « {equipment.name} » : il figure dans {loans}."
        ) from error


def _write(equipment: Equipment, data: EquipmentIn) -> None:
    equipment.name = data.name
    equipment.total_quantity = data.total_quantity
    equipment.repair_quantity = data.repair_quantity
    equipment.repair_note = data.repair_note


def _check_shortage(equipment: Equipment, repair: int) -> None:
    """Refuse a change that leaves a loan short, under the quantity changed:
    more pieces under repair, or else a lower total.
    """
    found = shortages([equipment])
    if not found:
        return
    [shortage] = found
    field = "repair_quantity" if equipment.repair_quantity > repair else "total_quantity"
    remaining = (
        f"il n’en resterait que {shortage.offered}"
        if shortage.offered
        else "il n’en resterait aucun"
    )
    edit = (
        "Modifiez d’abord ce prêt." if len(shortage.loans) == 1 else "Modifiez d’abord ces prêts."
    )
    loans = " ; ".join(_loan_label(loan) for loan in shortage.loans)
    raise ValidationError(
        {
            # The first day short, and the most the loans take from then on,
            # which may come later.
            field: f"Impossible : à partir du {shortage.day:%d/%m/%Y}, les prêts en prennent "
            f"jusqu’à {shortage.taken} ({loans}), {remaining}. {edit}"
        }
    )


def _loan_label(loan: Loan) -> str:
    """A loan as a message names it: its number and borrower, or its event."""
    return ", ".join(part for part in (loan.number, loan.display_name) if part)
