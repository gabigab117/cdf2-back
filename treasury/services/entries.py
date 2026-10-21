"""The entries of the ledger (A18), as the board records and corrects them.

An entry names its event, or none for the committee's general running. An
advance names the member who paid it, who stays named once they have left the
board, or once their account is deleted, as long as the advance keeps them.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.base import File
from django.db import transaction
from django.db.models import (
    Case,
    CharField,
    F,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)

from accounts.models import User
from documents.models import Document
from stock.models import StockMovement
from treasury.models import (
    LedgerCategory,
    LedgerEntry,
    LedgerEntryKind,
    LedgerPaymentMethod,
    LedgerReceiptState,
)
from treasury.schemas import LedgerEntryIn
from treasury.services.receipts import receipt_document

MEMBER_OF_ADVANCE = "Choisissez le membre qui a avancé la dépense."
HAS_RECEIPT = "Cette ligne a déjà son justificatif."
BELOW_STOCKED_COST = (
    "Le montant ne peut pas être plus petit que les prix des articles mis en stock."
)

# Where the receipt of an entry stands (6.2): an expense needs one, but for its
# bank fees; an income needs none, though one may be attached.
RECEIPT_STATE = Case(
    When(receipt__isnull=False, then=Value(LedgerReceiptState.ATTACHED)),
    When(
        Q(kind=LedgerEntryKind.INCOME) | Q(category=LedgerCategory.BANK_FEES),
        then=Value(LedgerReceiptState.NOT_REQUIRED),
    ),
    default=Value(LedgerReceiptState.MISSING),
    output_field=CharField(),
)


# What the stock purchase of an expense cost (D16): the share of the expense gone
# into stock. None for an expense that paid none: the subquery finds no line.
STOCKED_COST = Subquery(
    StockMovement.objects.filter(operation=OuterRef("stock_purchase"))
    .order_by()
    .values("operation")
    .annotate(total=Sum("cost", default=Decimal(0)))
    .values("total")
)


def ledger_entries() -> QuerySet[LedgerEntry]:
    """The entries as the ledger reads them, the latest first, with their
    event, their people, their receipt and where it stands, and the stock
    purchase an expense paid, with its share of the expense and what is left
    of it.
    """
    return (
        LedgerEntry.objects.select_related(
            "event", "advanced_by", "created_by", "receipt", "stock_purchase"
        )
        .annotate(receipt_state=RECEIPT_STATE, stocked_cost=STOCKED_COST)
        # None without a stock purchase, as its stocked cost.
        .annotate(unstocked_cost=F("amount") - F("stocked_cost"))
    )


def record_entry(data: LedgerEntryIn, member: User, file: File | None = None) -> LedgerEntry:
    """Record a new entry of a member, and its receipt with it if a file comes:
    both are written, or neither.
    """
    document = None
    try:
        with transaction.atomic():
            entry = _save(LedgerEntry(created_by=member), data)
            if file is not None:
                document = receipt_document(entry, file, member)
                _attach(entry, document)
    except BaseException:
        _forget(document)
        raise
    return ledger_entries().get(pk=entry.pk)


def attach_receipt(entry: LedgerEntry, file: File, member: User) -> LedgerEntry:
    """Attach the receipt of an entry that has none, such as the ticket of an
    expense found afterwards.
    """
    document = None
    try:
        with transaction.atomic():
            # Locked: two receipts attached at once, the second finds the first.
            entry = LedgerEntry.objects.select_for_update().get(pk=entry.pk)
            if entry.receipt_id is not None:
                raise ValidationError({"file": HAS_RECEIPT})
            document = receipt_document(entry, file, member)
            _attach(entry, document)
    except BaseException:
        _forget(document)
        raise
    return ledger_entries().get(pk=entry.pk)


def missing_receipts() -> QuerySet[LedgerEntry]:
    """The expenses whose receipt is missing, the oldest first: the bell and
    the treasury assistant ask for them.
    """
    return ledger_entries().filter(receipt_state=LedgerReceiptState.MISSING).order_by("date", "pk")


@transaction.atomic
def update_entry(entry: LedgerEntry, data: LedgerEntryIn) -> LedgerEntry:
    """Correct an entry whole. Its receipt, its reimbursement and its stock
    purchase stay as they are: its amount never falls below what that purchase
    cost (D16).
    """
    # Locked: what the entry holds besides its fields, its reimbursement and its
    # stock purchase, is read as it stands. The purchase's costs are read
    # without locking it: its own writes lock it before the entry.
    entry = (
        LedgerEntry.objects.select_for_update().annotate(stocked_cost=STOCKED_COST).get(pk=entry.pk)
    )
    entry = _save(entry, data, stocked_cost=entry.stocked_cost)
    return ledger_entries().get(pk=entry.pk)


def delete_entry(entry: LedgerEntry) -> None:
    """Delete an entry: its receipt stays among the documents."""
    entry.delete()


def _save(
    entry: LedgerEntry, data: LedgerEntryIn, stocked_cost: Decimal | None = None
) -> LedgerEntry:
    keeps_member = (
        entry.pk is not None
        and entry.payment_method == LedgerPaymentMethod.ADVANCE
        and data.payment_method == LedgerPaymentMethod.ADVANCE
        and entry.advanced_by_id == data.advanced_by
    )
    _write(entry, data)
    check_entry(entry, keeps_member=keeps_member, stocked_cost=stocked_cost)
    entry.save()
    return entry


def check_entry(
    entry: LedgerEntry, keeps_member: bool, stocked_cost: Decimal | None = None
) -> None:
    """Check an entry before it is written: its fields and constraints, as the
    model words them, the member of an advance, and, for an expense that paid a
    stock purchase, an amount never below what that purchase cost (D16).

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
    # An amount the model refuses already says why on its own.
    if stocked_cost is not None and "amount" not in errors and entry.amount < stocked_cost:
        errors["amount"] = [ValidationError(BELOW_STOCKED_COST)]
    if errors:
        raise ValidationError(errors)


def _attach(entry: LedgerEntry, document: Document) -> None:
    entry.receipt = document
    entry.save(update_fields=["receipt"])


def _forget(document: Document | None) -> None:
    # The record undone, its file goes too: record_document only removes it
    # when its own record fails.
    if document is not None:
        document.file.delete(save=False)


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
