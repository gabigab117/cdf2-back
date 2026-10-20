"""The advances of the board's members, until the committee pays them back
(6.5, A18).

An advance is an expense a member paid with their own money. Its reimbursement
completes it, with a date and a method: no second expense is written.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, QuerySet, Sum

from treasury.models import LedgerEntry, LedgerPaymentMethod
from treasury.schemas import ReimbursementIn
from treasury.services.entries import check_entry, ledger_entries

NOT_AN_ADVANCE = "Seule une avance se rembourse."
REIMBURSED = "Cette avance est déjà remboursée."
NOT_REIMBURSED = "Cette avance n’est pas remboursée."


def advances_to_reimburse() -> QuerySet[LedgerEntry]:
    """The advances the committee still owes, the oldest first."""
    return (
        ledger_entries()
        .filter(payment_method=LedgerPaymentMethod.ADVANCE, reimbursed_on__isnull=True)
        .order_by("date", "pk")
    )


def owed(advances: QuerySet[LedgerEntry]) -> tuple[int, Decimal]:
    """How many advances, and how much they add up to."""
    sums = advances.aggregate(count=Count("pk"), total=Sum("amount", default=Decimal("0.00")))
    return sums["count"], sums["total"]


@transaction.atomic
def mark_reimbursed(entry: LedgerEntry, data: ReimbursementIn) -> LedgerEntry:
    """« Marquer remboursée »: the advance is paid back on a day, by a method."""
    # Locked: two members marking it at once, the second finds it paid back.
    entry = LedgerEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.payment_method != LedgerPaymentMethod.ADVANCE:
        raise ValidationError(NOT_AN_ADVANCE)
    if entry.reimbursed_on is not None:
        raise ValidationError(REIMBURSED)
    entry.reimbursed_on = data.reimbursed_on
    entry.reimbursement_method = data.reimbursement_method
    check_entry(entry, keeps_member=True)
    entry.save(update_fields=["reimbursed_on", "reimbursement_method"])
    return ledger_entries().get(pk=entry.pk)


@transaction.atomic
def cancel_reimbursement(entry: LedgerEntry) -> LedgerEntry:
    """« Annuler le remboursement »: a click too many undone."""
    entry = LedgerEntry.objects.select_for_update().get(pk=entry.pk)
    if entry.reimbursed_on is None:
        raise ValidationError(NOT_REIMBURSED)
    entry.reimbursed_on = None
    entry.reimbursement_method = None
    entry.save(update_fields=["reimbursed_on", "reimbursement_method"])
    return ledger_entries().get(pk=entry.pk)
