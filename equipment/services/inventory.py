"""The committee's equipment, as the inventory lists and writes it.

An equipment written locks its row first (select_for_update), as a loan's
writes do: a change of its pieces cannot slip between a loan's reading of what
is free and its writing.
"""

import datetime as dt
from collections import Counter
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, ProtectedError, QuerySet, Value, When
from django.utils import timezone
from django.utils.translation import ngettext

from equipment.models import Equipment, EquipmentCategory, Loan
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
    """Today's inventory: what each equipment offers today, its figures, and how
    many equipment each category holds. A bounded aggregate (A7).
    """

    day: dt.date
    items: list[Availability]
    totals: InventoryTotals
    counts: dict[str, int]


@dataclass(frozen=True)
class Occupancy:
    """The loans that take an equipment over the weeks to come."""

    start: dt.date
    end: dt.date
    loans: list[Conflict]


def ordered_equipment() -> QuerySet[Equipment]:
    """The equipment in the inventory's order: by category, in the order of the
    chips, then by name.
    """
    category_order = Case(
        *(
            When(category=category, then=Value(index))
            for index, category in enumerate(EquipmentCategory.values)
        )
    )
    return Equipment.objects.order_by(category_order, "name", "pk")


def inventory(*, today: dt.date | None = None) -> Inventory:
    """What each equipment offers today, with the figures of the inventory."""
    today = today or timezone.localdate()
    items = availability(ordered_equipment(), today, today, today=today)
    categories = Counter(item.equipment.category for item in items)
    return Inventory(
        day=today,
        items=items,
        totals=InventoryTotals(
            references=len(items),
            taken_today=sum(1 for item in items if item.taken),
            pieces_under_repair=sum(item.equipment.repair_quantity for item in items),
        ),
        counts={"total": len(items)}
        | {category: categories[category] for category in EquipmentCategory.values},
    )


def occupancy(equipment: Equipment, *, today: dt.date | None = None) -> Occupancy:
    """The loans that take an equipment, from the Monday of this week, for
    eleven weeks.
    """
    today = today or timezone.localdate()
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
    offered = equipment.total_quantity - equipment.repair_quantity
    repair = equipment.repair_quantity
    _write(equipment, data)
    equipment.full_clean()
    if equipment.total_quantity - equipment.repair_quantity < offered:
        _check_shortage(equipment, repair)
    equipment.save()
    return equipment


def delete_equipment(equipment: Equipment) -> None:
    """Delete an equipment no loan names: the loans keep their history."""
    # PROTECT refuses it before any deletion: the transaction stays usable.
    try:
        equipment.delete()
    except ProtectedError as error:
        loans = len(error.protected_objects)
        raise ValidationError(
            ngettext(
                "Impossible de supprimer « %(name)s » : il figure dans %(count)d prêt.",
                "Impossible de supprimer « %(name)s » : il figure dans %(count)d prêts.",
                loans,
            )
            % {"name": equipment.name, "count": loans}
        ) from error


def _write(equipment: Equipment, data: EquipmentIn) -> None:
    equipment.name = data.name
    equipment.category = data.category
    equipment.storage_location = data.storage_location
    equipment.total_quantity = data.total_quantity
    equipment.repair_quantity = data.repair_quantity
    equipment.unit_value = data.unit_value
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
    edit = ngettext("Modifiez d’abord ce prêt.", "Modifiez d’abord ces prêts.", len(shortage.loans))
    loans = " ; ".join(_loan_label(loan) for loan in shortage.loans)
    raise ValidationError(
        {
            field: f"Impossible : les prêts en prennent {shortage.taken} le "
            f"{shortage.day:%d/%m/%Y} ({loans}), {remaining}. {edit}"
        }
    )


def _loan_label(loan: Loan) -> str:
    """A loan as a message names it: its number and borrower, or its event."""
    return ", ".join(part for part in (loan.number, loan.display_name) if part)
