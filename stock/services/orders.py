"""The orders of the stock (7.4): the lines of an order, each an item and how
much of it, entered by hand before the assistant (A19), then received into the
stock in one click.

A delivery is undone the day it was received, until midnight in Paris, unless
one of its items has moved since, or a stocktake has counted it since.
"""

import datetime as dt
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Prefetch, Q, QuerySet
from django.utils import timezone

from accounts.models import User
from core.errors import line_errors
from documents.models import Document, DocumentCategory, DocumentStatus
from events.models import Event
from stock.models import (
    ALREADY_RECEIVED,
    ORDER_ITEM_TWICE,
    OrderLine,
    StockMovement,
    StockOperation,
    StockOperationReason,
)
from stock.schemas import OrderLinesIn
from stock.services.movements import lock

RECEIVED = "Cette commande est déjà réceptionnée : annulez d’abord la réception."


@dataclass(frozen=True)
class Order:
    """An order of the stock, as its document tells it, with its lines and its
    delivery.
    """

    # The id of its document.
    id: int
    title: str
    issuer: str
    delivery_date: dt.date | None
    event: Event | None
    validated: bool
    lines: list[OrderLine]
    # None until it is received.
    delivery: StockOperation | None
    # Received today: « Annuler » until midnight.
    undoable: bool


def orders() -> QuerySet[Document]:
    """The order documents, with their event, their lines and their delivery."""
    return (
        Document.objects.filter(category=DocumentCategory.ORDER)
        .select_related("event")
        .prefetch_related(
            Prefetch(
                "order_lines", queryset=OrderLine.objects.select_related("item").order_by("pk")
            ),
            Prefetch(
                "stock_operations",
                queryset=StockOperation.objects.filter(
                    reason=StockOperationReason.DELIVERY
                ).select_related("author"),
                to_attr="deliveries",
            ),
        )
    )


def order(document: Document, *, today: dt.date | None = None) -> Order:
    """An order read by orders(), with whether its delivery may still be undone."""
    today = today or timezone.localdate()
    delivery = next(iter(document.deliveries), None)
    # The delivery date lives among what belongs to an order alone (extracted).
    delivery_date = document.extracted.get("delivery_date")
    return Order(
        id=document.pk,
        title=document.title,
        issuer=document.issuer,
        delivery_date=dt.date.fromisoformat(delivery_date) if delivery_date else None,
        event=document.event,
        validated=document.status == DocumentStatus.VALIDATED,
        lines=list(document.order_lines.all()),
        delivery=delivery,
        undoable=delivery is not None and timezone.localtime(delivery.created_at).date() == today,
    )


def orders_to_receive() -> list[Order]:
    """The orders the Stock page shows: those validated with lines, not received
    yet, the first delivered first; then those received today, which « Annuler »
    still undoes.
    """
    today = timezone.localdate()
    received_today = Q(
        stock_operations__reason=StockOperationReason.DELIVERY,
        stock_operations__created_at__date=today,
    )
    to_receive = Q(status=DocumentStatus.VALIDATED, order_lines__isnull=False) & ~Q(
        stock_operations__reason=StockOperationReason.DELIVERY
    )
    found = [
        order(document, today=today)
        for document in orders().filter(to_receive | received_today).distinct()
    ]
    # Ordered here, on what order() reads: received or not, then the delivery
    # date, an order without one last.
    return sorted(
        found,
        key=lambda entry: (
            entry.delivery is not None,
            entry.delivery_date or dt.date.max,
            entry.id,
        ),
    )


@transaction.atomic
def replace_lines(document: Document, data: OrderLinesIn) -> Order:
    """Rewrite the lines of an order, all at once, until it is received. Without
    any line, the order leaves the Stock page.
    """
    document = _locked(document)
    if document.deliveries:
        raise ValidationError(RECEIVED)
    lines = [
        OrderLine(document=document, item_id=line.item, quantity=line.quantity)
        for line in data.lines
    ]
    _check(lines)
    document.order_lines.all().delete()
    OrderLine.objects.bulk_create(lines)
    return order(orders().get(pk=document.pk))


@transaction.atomic
def receive(document: Document, member: User) -> Order:
    """« Réceptionner la livraison »: each line of a validated order comes into
    the stock, by a single delivery of the member, with the order and its event.
    """
    document = _locked(document)
    if document.status != DocumentStatus.VALIDATED:
        raise ValidationError("Validez d’abord la commande.")
    # Read under the lock: the constraint would place its error under the
    # document, which no form shows.
    if document.deliveries:
        raise ValidationError(ALREADY_RECEIVED)
    lines = list(document.order_lines.all())
    if not lines:
        raise ValidationError("Cette commande n’a aucune ligne de stock.")
    lock(line.item_id for line in lines)
    delivery = StockOperation.objects.create(
        reason=StockOperationReason.DELIVERY,
        label=document.title,
        event_id=document.event_id,
        document=document,
        author=member,
    )
    StockMovement.objects.bulk_create(
        StockMovement(operation=delivery, item_id=line.item_id, delta=line.quantity)
        for line in lines
    )
    return order(orders().get(pk=document.pk))


@transaction.atomic
def cancel_delivery(document: Document) -> Order:
    """« Annuler »: undo the delivery of an order, the day it was received,
    unless one of its items has moved, or a stocktake has counted it, since.
    """
    current = order(_locked(document))
    delivery = current.delivery
    if delivery is None:
        raise ValidationError("Cette commande n’est pas réceptionnée.")
    if not current.undoable:
        raise ValidationError("Une réception ne s’annule que le jour même.")
    # Locked after its order, before its items: a member writing its costs, who
    # locks it too (D16), waits, rather than meeting the deletion of its lines.
    delivery = StockOperation.objects.select_for_update().get(pk=delivery.pk)
    # Locked next: a stocktake of these items, which locks them too, comes
    # either before, and is found below, or once the delivery is undone.
    locked = lock(movement.item_id for movement in delivery.movements.all())
    # A stocktake that came after counted what was delivered, whether it found
    # a difference or not: undoing the delivery would make its counts wrong.
    if StockOperation.objects.filter(
        reason=StockOperationReason.STOCKTAKE, created_at__gt=delivery.created_at
    ).exists():
        raise ValidationError("Un inventaire a suivi cette réception : elle ne s’annule plus.")
    # Undone, a delivery leaves the end of each item's history alone: an item
    # that moved since may have spent what came, even bought back since, and
    # without the delivery its history, which the valuation replays (D16),
    # would go below zero.
    moved = (
        StockMovement.objects.filter(
            item_id__in=locked, operation__created_at__gt=delivery.created_at
        )
        .values_list("item__name", flat=True)
        .distinct()
        .order_by("item__name")
    )
    if names := ", ".join(f"« {name} »" for name in moved):
        raise ValidationError(
            f"Le stock a bougé depuis cette réception ({names}) : elle ne s’annule plus."
        )
    delivery.delete()
    return order(orders().get(pk=document.pk))


def _locked(document: Document) -> Document:
    """Lock an order first, then read its lines and its delivery."""
    # Its event, an outer join, is read without being locked.
    return orders().select_for_update(of=("self",)).get(pk=document.pk)


def _check(lines: list[OrderLine]) -> None:
    """Check each line of an order: its item exists and comes once, its quantity
    is above zero, to the hundredth. Every error at once, a line's under its
    position: "lines.1.quantity".
    """
    errors: dict[str, list[str]] = {}
    # The lines are written anew: their unique constraint with the order is
    # checked here, among the lines of the request.
    seen: set[int] = set()
    for index, line in enumerate(lines):
        errors |= line_errors("lines", index, line, {"document"})
        if line.item_id in seen:
            errors.setdefault(f"lines.{index}.item", []).append(ORDER_ITEM_TWICE)
        seen.add(line.item_id)
    if errors:
        raise ValidationError(errors)
