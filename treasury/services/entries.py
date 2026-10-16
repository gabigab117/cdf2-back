"""The entries of the journal (A18), as the board records and corrects them.

An entry names its event, or none for the committee's general running. An
advance names the member who paid it, who stays named once they have left the
board, or once their account is deleted, as long as the advance keeps them.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet

from accounts.models import User
from treasury.models import LedgerEntry, LedgerPaymentMethod
from treasury.schemas import LedgerEntryIn

MEMBER_OF_ADVANCE = "Choisissez le membre qui a avancé la dépense."


def ledger_entries() -> QuerySet[LedgerEntry]:
    """The entries as the journal reads them, the latest first, with their
    event and their people.
    """
    return LedgerEntry.objects.select_related("event", "advanced_by", "created_by")


def record_entry(data: LedgerEntryIn, member: User) -> LedgerEntry:
    """Record a new entry of a member."""
    return _save(LedgerEntry(created_by=member), data)


@transaction.atomic
def update_entry(entry: LedgerEntry, data: LedgerEntryIn) -> LedgerEntry:
    """Correct an entry whole. Its receipt and its reimbursement stay as they are."""
    # Locked: what the entry holds besides its fields, its reimbursement, is
    # read as it stands.
    return _save(LedgerEntry.objects.select_for_update().get(pk=entry.pk), data)


def delete_entry(entry: LedgerEntry) -> None:
    """Delete an entry: its receipt stays among the documents."""
    entry.delete()


def _save(entry: LedgerEntry, data: LedgerEntryIn) -> LedgerEntry:
    keeps_member = (
        entry.pk is not None
        and entry.payment_method == LedgerPaymentMethod.ADVANCE
        and data.payment_method == LedgerPaymentMethod.ADVANCE
        and entry.advanced_by_id == data.advanced_by
    )
    _write(entry, data)
    _check(entry, keeps_member=keeps_member)
    entry.save()
    return ledger_entries().get(pk=entry.pk)


def _check(entry: LedgerEntry, keeps_member: bool) -> None:
    """Check an entry before it is written: its fields and constraints, as the
    model words them, and the member of an advance.

    The database cannot require that member: a deleted account leaves its
    advances behind without one. Whoever is named already, a member who has left
    the board or none, stays named while the advance keeps them.
    """
    errors: dict = {}
    try:
        # Excluded, the member is not checked against the board, and the
        # constraints that name it are skipped: they hold already, the entry
        # being an advance of that member.
        entry.full_clean(exclude={"advanced_by"} if keeps_member else None)
    except ValidationError as error:
        errors = error.update_error_dict(errors)
    advance = entry.payment_method == LedgerPaymentMethod.ADVANCE
    if advance and entry.advanced_by_id is None and not keeps_member:
        errors.setdefault("advanced_by", []).append(ValidationError(MEMBER_OF_ADVANCE))
    if errors:
        raise ValidationError(errors)


def _write(entry: LedgerEntry, data: LedgerEntryIn) -> None:
    entry.date = data.date
    entry.kind = data.kind
    entry.label = data.label
    entry.amount = data.amount
    entry.category = data.category
    entry.payment_method = data.payment_method
    entry.advanced_by_id = data.advanced_by
    entry.event_id = data.event
    entry.supplier = data.supplier
    entry.note = data.note
