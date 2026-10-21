"""The operations of the stock (7.2): an entry or an exit of several items at
once, and a stocktake, each a single operation of its member; and the costs of
a purchase or a delivery, completed or corrected (D16).

An entry, an exit and a stocktake lock their items first, by key, then sum their
movements: no quantity goes below zero. The costs lock their operation alone:
they move no quantity.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.validators import DecimalValidator, MinValueValidator
from django.db import models, transaction
from django.db.models import Case, Exists, OuterRef, Prefetch, Q, QuerySet, Value, When
from django.utils.formats import number_format

from accounts.models import User
from events.models import Event
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
from stock.schemas import StockCostsIn, StockOperationIn, StocktakeIn
from stock.services.movements import NOTHING_LEFT, lock, quantities
from stock.services.valuation import NO_VALUE, PRICED_REASONS, valued_movements

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
# What the line of a purchase cost (D16), as its movement keeps it, to the cent:
# a prize given costs nothing.
COSTS = StockMovement._meta.get_field("cost").validators
PURCHASE_COST_ONLY = "Seul un achat a un prix."
PRICED_ONLY = "Seuls un achat et une réception ont des prix."
NOT_IN_OPERATION = "Cet article n’est pas dans l’opération."
EVERY_LINE = "Donnez le prix de chaque ligne de l’opération, ou laissez-le vide."
PAID_BY_EXPENSE = "Cet achat est payé par une dépense : ses prix se corrigent depuis elle."

Rows = list[tuple[int, Decimal]]

# A purchase or a delivery waiting for the cost of a line (D16).
UNPRICED = Q(
    Exists(StockMovement.objects.filter(operation=OuterRef("pk"), cost__isnull=True)),
    reason__in=PRICED_REASONS,
)


@dataclass(frozen=True)
class OperationLine:
    """A line of an operation, valued: what it moved of an item, and at what cost."""

    item: StockItem
    delta: Decimal
    # What the line of a purchase or a delivery cost; None while unknown.
    cost: Decimal | None
    # The unit cost it moved at, to the ten-thousandth, and what it moved, to
    # the cent; None for an item whose stock has no cost to come at.
    unit_cost: Decimal | None
    value: Decimal | None
    # A line of a purchase or a delivery waiting for its cost.
    unpriced: bool


@dataclass(frozen=True)
class OperationDetail:
    """An operation, as its page shows it: its lines valued."""

    id: int
    reason: str
    label: str
    event: Event | None
    author: User | None
    created_at: dt.datetime
    unpriced: bool
    # A purchase or a delivery: the costs of its lines are completed or corrected.
    priceable: bool
    # What the lines that have a cost cost, in all.
    cost: Decimal
    lines: list[OperationLine]
    # The ledger entry that paid it (D16), read by its reverse relation: the
    # stock imports nothing of the treasury. None for none.
    expense: models.Model | None


def operations() -> QuerySet[StockOperation]:
    """The operations, the latest first, with their event, their member, their
    movements in the order they were written, and whether they wait for a cost.
    """
    movements = StockMovement.objects.select_related("item").order_by("pk")
    return (
        # The expense that paid a purchase (D16), from the treasury.
        StockOperation.objects.select_related("event", "author", "ledger_entry")
        .annotate(unpriced=Case(When(UNPRICED, then=Value(True)), default=Value(False)))
        .prefetch_related(Prefetch("movements", queryset=movements))
    )


def unpriced_purchases() -> QuerySet[StockOperation]:
    """The purchases and deliveries waiting for the cost of a line, the oldest
    first, with their member: what the bell asks for (A6).
    """
    return (
        StockOperation.objects.filter(UNPRICED)
        .select_related("author")
        .order_by("created_at", "pk")
    )


def operation_detail(operation: StockOperation) -> OperationDetail:
    """An operation read by operations(), its lines valued at the cost of their
    time.
    """
    movements = list(operation.movements.all())
    histories = valued_movements(movement.item_id for movement in movements)
    valued = {line.id: line for history in histories.values() for line in history}
    lines = [
        OperationLine(
            item=movement.item,
            delta=movement.delta,
            cost=movement.cost,
            unit_cost=valued[movement.pk].unit_cost,
            value=valued[movement.pk].value,
            unpriced=valued[movement.pk].unpriced,
        )
        for movement in movements
    ]
    return OperationDetail(
        id=operation.pk,
        reason=operation.reason,
        label=operation.label,
        event=operation.event,
        author=operation.author,
        created_at=operation.created_at,
        unpriced=any(line.unpriced for line in lines),
        priceable=operation.reason in PRICED_REASONS,
        cost=sum((line.cost for line in lines if line.cost is not None), NO_VALUE),
        lines=lines,
        expense=paid_by(operation),
    )


def lock_operation(operation_id: int) -> StockOperation:
    """Lock an operation, then read it as operations() does: its lines, and
    the expense that paid it.
    """
    # Its event and its expense, outer joins, are read without being locked.
    return operations().select_for_update(of=("self",)).get(pk=operation_id)


def paid_by(operation: StockOperation) -> models.Model | None:
    """The ledger entry that paid an operation (D16), or None."""
    return getattr(operation, "ledger_entry", None)


def recent_operations() -> list[StockOperation]:
    """The latest operations, as « Mouvements récents » lists them."""
    return list(operations()[:RECENT_OPERATIONS_COUNT])


@transaction.atomic
def record_operation(data: StockOperationIn, member: User) -> StockOperation:
    """« Entrée ou sortie »: several items in or out at once, for one reason,
    recorded with its member. An exit never takes more than is in stock; a
    purchase may tell what each line cost (D16).
    """
    reason = StockOperationReason(data.reason)
    operation = StockOperation(reason=reason, label=data.label, event_id=data.event, author=member)
    rows = [(line.item, line.quantity) for line in data.lines]
    locked, errors = _checked(operation, rows, "lines", "quantity", SOME)
    errors |= _cost_errors(
        [line.cost for line in data.lines], allowed=reason == StockOperationReason.PURCHASE
    )
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
        StockMovement(
            operation=operation, item_id=line.item, delta=sign * line.quantity, cost=line.cost
        )
        for line in data.lines
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


@transaction.atomic
def update_costs(operation: StockOperation, data: StockCostsIn) -> OperationDetail:
    """« Compléter les prix », « Corriger les prix »: what each line of a purchase
    or a delivery cost, all at once (D16), the only correction of an operation.
    Its quantities stay as they are, and every value follows. A purchase an
    expense paid has its costs corrected from that expense.
    """
    operation = lock_operation(operation.pk)
    if paid_by(operation) is not None:
        raise ValidationError(PAID_BY_EXPENSE)
    save_costs(operation, data)
    # Its prefetched lines hold their new costs: the values are read anew.
    return operation_detail(operation)


def save_costs(operation: StockOperation, data: StockCostsIn) -> None:
    """Write what each line of an operation locked by lock_operation() cost:
    every line given once, each cost within bounds, or none of them.
    """
    if operation.reason not in PRICED_REASONS:
        raise ValidationError(PRICED_ONLY)
    movements = {movement.item_id: movement for movement in operation.movements.all()}
    errors: dict[str, list[str]] = {}
    seen: set[int] = set()
    for index, line in enumerate(data.lines):
        if line.item not in movements:
            errors[f"lines.{index}.item"] = [NOT_IN_OPERATION]
        elif line.item in seen:
            errors[f"lines.{index}.item"] = [ITEM_TWICE]
        seen.add(line.item)
    if movements.keys() - seen:
        errors[NON_FIELD_ERRORS] = [EVERY_LINE]
    errors |= _cost_errors([line.cost for line in data.lines])
    if errors:
        raise ValidationError(errors)
    for line in data.lines:
        movements[line.item].cost = line.cost
    StockMovement.objects.bulk_update(movements.values(), ["cost"])


def _cost_errors(costs: list[Decimal | None], *, allowed: bool = True) -> dict[str, list[str]]:
    """Check the cost of each line, under its position: where a cost is allowed,
    never negative, to the cent. A line without one waits for it.
    """
    errors: dict[str, list[str]] = {}
    for index, cost in enumerate(costs):
        if cost is None:
            continue
        if not allowed:
            errors[f"lines.{index}.cost"] = [PURCHASE_COST_ONLY]
            continue
        try:
            for validate in COSTS:
                validate(cost)
        except ValidationError as error:
            errors[f"lines.{index}.cost"] = error.messages
    return errors


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
