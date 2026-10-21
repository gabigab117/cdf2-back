"""The stock purchase an expense paid (D16): « Mettre en stock » records it
from the expense, « Achat déjà saisi » links one recorded in the stock and
completes its costs. Its costs never add up to more than the expense; what is
left is a direct charge.

The locks keep one order: the stock operation, then the expense, then the
items.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet

from accounts.models import User
from stock.models import StockOperation
from stock.schemas import StockCostIn, StockCostsIn, StockLineIn, StockOperationIn
from stock.services.operations import (
    lock_operation,
    operations,
    paid_by,
    record_operation,
    save_costs,
)
from stock.services.valuation import PRICED_REASONS
from treasury.models import (
    PAID_BY_ANOTHER,
    STOCK_PURCHASE_OF_EXPENSE,
    LedgerEntry,
    LedgerEntryKind,
)
from treasury.schemas import (
    ExistingPurchaseIn,
    ExistingPurchaseLineIn,
    StockPurchaseIn,
    StockPurchaseLineIn,
)
from treasury.services.entries import ledger_entries

PAYS_ANOTHER = "Cette dépense paie déjà un autre achat du stock."
NO_PURCHASE = "Choisissez un achat ou une réception du stock."
ABOVE_AMOUNT = "Les prix des articles dépassent le montant de la dépense."


def unlinked_purchases() -> QuerySet[StockOperation]:
    """The purchases and deliveries no expense paid yet, the latest first: what
    « Achat déjà saisi » chooses from.
    """
    return operations().filter(reason__in=PRICED_REASONS, ledger_entry__isnull=True)


@transaction.atomic
def create_stock_purchase(entry: LedgerEntry, data: StockPurchaseIn, member: User) -> LedgerEntry:
    """« Mettre en stock »: a purchase recorded from an expense, with its label
    and its event, each line with its cost, all of them within the expense.
    """
    entry = _locked_expense(entry)
    operation = record_operation(
        StockOperationIn(
            direction="in",
            reason="purchase",
            label=entry.label,
            event=entry.event_id,
            lines=[
                StockLineIn(item=line.item, quantity=line.quantity, cost=line.cost)
                for line in data.lines
            ],
        ),
        member,
    )
    _within(data.lines, entry)
    return _linked(entry, operation)


@transaction.atomic
def link_existing_purchase(entry: LedgerEntry, data: ExistingPurchaseIn) -> LedgerEntry:
    """« Achat déjà saisi »: a purchase or a delivery recorded in the stock,
    paid by this expense, its costs given whole. Given again, its costs are
    corrected.
    """
    try:
        operation = lock_operation(data.operation)
    except StockOperation.DoesNotExist:
        raise ValidationError({"operation": [NO_PURCHASE]}) from None
    if paid_by(operation) not in (None, entry):
        raise ValidationError({"operation": [PAID_BY_ANOTHER]})
    entry = _locked_expense(entry, operation.pk)
    save_costs(
        operation,
        StockCostsIn(lines=[StockCostIn(item=line.item, cost=line.cost) for line in data.lines]),
    )
    _within(data.lines, entry)
    return _linked(entry, operation)


@transaction.atomic
def unlink_stock_purchase(entry: LedgerEntry) -> LedgerEntry:
    """« Retirer »: the expense pays the purchase no more. The purchase stays in
    the stock, with its costs.
    """
    entry = LedgerEntry.objects.select_for_update().get(pk=entry.pk)
    entry.stock_purchase = None
    entry.save(update_fields=["stock_purchase"])
    return ledger_entries().get(pk=entry.pk)


def _locked_expense(entry: LedgerEntry, operation_id: int | None = None) -> LedgerEntry:
    """Lock an expense that may pay a stock purchase: none yet, or this one."""
    entry = LedgerEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.kind != LedgerEntryKind.EXPENSE:
        raise ValidationError(STOCK_PURCHASE_OF_EXPENSE)
    if entry.stock_purchase_id not in (None, operation_id):
        raise ValidationError(PAYS_ANOTHER)
    return entry


def _within(
    lines: list[StockPurchaseLineIn] | list[ExistingPurchaseLineIn], entry: LedgerEntry
) -> None:
    """Refuse costs that add up to more than the expense."""
    if sum((line.cost for line in lines), Decimal(0)) > entry.amount:
        raise ValidationError(ABOVE_AMOUNT)


def _linked(entry: LedgerEntry, operation: StockOperation) -> LedgerEntry:
    entry.stock_purchase = operation
    entry.save(update_fields=["stock_purchase"])
    return ledger_entries().get(pk=entry.pk)
