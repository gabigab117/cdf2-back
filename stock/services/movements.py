"""The movements of the stock (A19).

Every write locks the items it moves first (select_for_update), by key: two
writes never wait on each other in a circle, and the quantity one reads does not
change before it writes. It then sums their movements, in a second query, as
PostgreSQL locks no grouped rows: no quantity ever goes below zero.
"""

from collections.abc import Iterable
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum

from accounts.models import User
from stock.models import (
    StockDirection,
    StockItem,
    StockMovement,
    StockOperation,
    StockOperationReason,
)
from stock.services.items import NOTHING, StockedItem, stock_items, stocked
from stock.services.valuation import valued_movements

NOTHING_LEFT = "Il n’en reste plus en stock."


def lock(item_ids: Iterable[int]) -> dict[int, StockItem]:
    """Lock the items a write moves, by key, and read them as they stand."""
    locked = StockItem.objects.select_for_update().filter(pk__in=item_ids).order_by("pk")
    return {item.pk: item for item in locked}


def quantities(item_ids: Iterable[int]) -> dict[int, Decimal]:
    """The quantity of each item: the sum of its movements, zero without any."""
    ids = list(item_ids)
    sums = dict(
        StockMovement.objects.filter(item_id__in=ids).values_list("item").annotate(Sum("delta"))
    )
    return {item_id: sums.get(item_id, NOTHING) for item_id in ids}


@transaction.atomic
def adjust(item: StockItem, direction: StockDirection, member: User) -> StockedItem:
    """A click on minus or plus (7.1): an adjustment of the item's step, in or out,
    recorded with its member. Out, it takes what is left when less than a step
    is: never below zero, as the mockup clamps it.
    """
    item = lock([item.pk])[item.pk]
    if direction == StockDirection.IN:
        delta = item.step
    else:
        delta = -min(item.step, quantities([item.pk])[item.pk])
        # Two clicks sent at once: the second finds nothing left.
        if not delta:
            raise ValidationError(NOTHING_LEFT)
    operation = StockOperation.objects.create(reason=StockOperationReason.ADJUSTMENT, author=member)
    StockMovement.objects.create(operation=operation, item=item, delta=delta)
    return stocked(stock_items().get(pk=item.pk), valued_movements([item.pk])[item.pk])
