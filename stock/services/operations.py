"""The operations of the stock (7.2): an entry or an exit of several items at
once, and a stocktake, each a single operation of its member.

Like every write of the stock, each locks its items first, by key, then sums
their movements: no quantity goes below zero.
"""

from decimal import Decimal

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.validators import DecimalValidator, MinValueValidator
from django.db import transaction
from django.db.models import Prefetch, QuerySet
from django.utils.formats import number_format

from accounts.models import User
from stock.models import (
    ITEM_TWICE,
    NO_QUANTITY,
    UNKNOWN_ITEM,
    StockDirection,
    StockItem,
    StockMovement,
    StockOperation,
    StockOperationReason,
)
from stock.schemas import StockOperationIn, StocktakeIn
from stock.services.movements import NOTHING_LEFT, lock, quantities

# How many operations « Mouvements récents » shows.
RECENT_OPERATIONS_COUNT = 5

# An operation without any row, by the name of its rows.
NO_ROW = {"lines": "Ajoutez au moins un article.", "counts": "Comptez au moins un article."}

# The direction each reason of an entry or an exit takes: a purchase comes in,
# a consumption goes out, an adjustment either way.
WRONG_DIRECTIONS = {
    (StockOperationReason.PURCHASE, StockDirection.OUT): "Un achat entre dans le stock.",
    (StockOperationReason.CONSUMPTION, StockDirection.IN): "Une consommation sort du stock.",
}

# The quantities of the stock, to the hundredth, as its movements keep them.
DELTA = StockMovement._meta.get_field("delta")
HUNDREDTHS = DecimalValidator(DELTA.max_digits, DELTA.decimal_places)
# What an entry or an exit moves; what a stocktake counts, nothing included.
SOME = (MinValueValidator(Decimal("0.01"), NO_QUANTITY), HUNDREDTHS)
ANY = (MinValueValidator(Decimal(0)), HUNDREDTHS)

Rows = list[tuple[int, Decimal]]


def operations() -> QuerySet[StockOperation]:
    """The operations, the latest first, with their event, their member, and
    their movements in the order they were written.
    """
    movements = StockMovement.objects.select_related("item").order_by("pk")
    return StockOperation.objects.select_related("event", "author").prefetch_related(
        Prefetch("movements", queryset=movements)
    )


def recent_operations() -> list[StockOperation]:
    """The latest operations, as « Mouvements récents » lists them."""
    return list(operations()[:RECENT_OPERATIONS_COUNT])


@transaction.atomic
def record_operation(data: StockOperationIn, member: User) -> StockOperation:
    """« Entrée ou sortie »: several items in or out at once, for one reason,
    recorded with its member. An exit never takes more than is in stock.
    """
    reason = StockOperationReason(data.reason)
    operation = StockOperation(reason=reason, label=data.label, event_id=data.event, author=member)
    rows = [(line.item, line.quantity) for line in data.lines]
    locked, errors = _checked(operation, rows, "lines", "quantity", SOME)
    wrong_direction = WRONG_DIRECTIONS.get((reason, data.direction))
    if wrong_direction:
        errors["reason"] = [wrong_direction]
    if errors:
        raise ValidationError(errors)
    sign = 1 if data.direction == StockDirection.IN else -1
    if sign < 0:
        _refuse_beyond(rows, locked)
    operation.save()
    StockMovement.objects.bulk_create(
        StockMovement(operation=operation, item_id=item, delta=sign * quantity)
        for item, quantity in rows
    )
    return operations().get(pk=operation.pk)


@transaction.atomic
def record_stocktake(data: StocktakeIn, member: User) -> StockOperation:
    """« Faire l'inventaire »: each difference between what was counted and what
    the stock held becomes a movement of a single stocktake. It is recorded
    even without any difference: it dates the stock.
    """
    operation = StockOperation(
        reason=StockOperationReason.STOCKTAKE,
        label=data.label,
        event_id=data.event,
        author=member,
    )
    rows = [(count.item, count.counted) for count in data.counts]
    locked, errors = _checked(operation, rows, "counts", "counted", ANY)
    if errors:
        raise ValidationError(errors)
    held = quantities(locked)
    operation.save()
    StockMovement.objects.bulk_create(
        StockMovement(operation=operation, item_id=item, delta=counted - held[item])
        for item, counted in rows
        if counted != held[item]
    )
    return operations().get(pk=operation.pk)


def _checked(
    operation: StockOperation, rows: Rows, prefix: str, field: str, bounds: tuple
) -> tuple[dict[int, StockItem], dict[str, list[str]]]:
    """Lock the items of an operation's rows, by key, and check the operation
    and each of its rows: its item exists and comes once, its quantity is
    within bounds. Every error at once, a row's under its position:
    "lines.1.quantity".
    """
    errors: dict[str, list[str]] = {}
    try:
        operation.full_clean()
    except ValidationError as error:
        errors |= error.message_dict
    locked = lock({item for item, _ in rows})
    # The operation is not recorded yet: its unique constraint with an item is
    # checked here, among the rows of the request, and an item by the locked
    # ones, read once for every row.
    seen: set[int] = set()
    for index, (item, quantity) in enumerate(rows):
        if item not in locked:
            errors[f"{prefix}.{index}.item"] = [UNKNOWN_ITEM]
        elif item in seen:
            errors[f"{prefix}.{index}.item"] = [ITEM_TWICE]
        seen.add(item)
        try:
            for validate in bounds:
                validate(quantity)
        except ValidationError as error:
            errors[f"{prefix}.{index}.{field}"] = error.messages
    if not rows:
        errors[NON_FIELD_ERRORS] = [NO_ROW[prefix]]
    return locked, errors


def _refuse_beyond(rows: Rows, locked: dict[int, StockItem]) -> None:
    """Refuse the rows of an exit that take more than is in stock, each under
    its position.
    """
    held = quantities(locked)
    beyond = {
        f"lines.{index}.quantity": [_left(locked[item], held[item])]
        for index, (item, quantity) in enumerate(rows)
        if quantity > held[item]
    }
    if beyond:
        raise ValidationError(beyond)


def _left(item: StockItem, quantity: Decimal) -> str:
    """« Il n'en reste que 1,5 kg en stock. »: a quantity the French way, with
    its unit, by the number format of the project's language.
    """
    if quantity <= 0:
        return NOTHING_LEFT
    figure = number_format(quantity.normalize(), force_grouping=True)
    # The unit never parts from its figure at the end of a line.
    unit = f"\u00a0{item.unit}" if item.unit else ""
    return f"Il n’en reste que {figure}{unit} en stock."
