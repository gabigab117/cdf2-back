"""The committee's equipment, as the inventory lists it."""

from django.db.models import Case, QuerySet, Value, When

from equipment.models import Equipment, EquipmentCategory


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
