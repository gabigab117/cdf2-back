"""The invoices of the documents, as the treasury records them (6.2, A18).

A validated invoice becomes an expense at the date it was paid: « Valider et
créer l'écriture » for one paid already, « Marquer payée » later for one to pay.
Until then it is « à régler », with its due date, unless it was taken over from
the v1, whose archives the treasury leaves aside (decision of 16/10/2026).

An invoice may also become the receipt of an expense entered by hand before it
came, such as a sworn statement made for a lost ticket (D14): it is attached to
that entry rather than recorded twice.
"""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import BooleanField, Case, F, QuerySet, Value, When

from accounts.models import User
from documents.models import Document, DocumentCategory, DocumentSource, DocumentStatus
from documents.services.documents import documents, mark_validated
from treasury.models import LedgerEntry, LedgerEntryKind
from treasury.schemas import InvoiceAttachIn, InvoiceExpenseIn
from treasury.services.entries import check_entry

NOT_AN_INVOICE = "Seule une facture devient une dépense."
HAS_EXPENSE = "Cette facture a déjà sa dépense."
NO_AMOUNT = "Indiquez le montant de la facture avant de créer sa dépense."
NOT_AN_OPEN_EXPENSE = "Choisissez une dépense sans justificatif."

# The fields of the expense, as the member typed them for the invoice.
FIELDS = {"date": "paid_on"}


def create_invoice_expense(document: Document, data: InvoiceExpenseIn, member: User) -> Document:
    """The expense of an invoice, at the date it was paid, the invoice as its
    receipt. An invoice that awaited review is validated with it.
    """
    with transaction.atomic():
        document = _locked_invoice(document)
        if not document.amount:
            raise ValidationError(NO_AMOUNT)
        entry = LedgerEntry(
            date=data.paid_on,
            kind=LedgerEntryKind.EXPENSE,
            label=data.label,
            amount=document.amount,
            category=data.category,
            payment_method=data.payment_method,
            advanced_by_id=data.advanced_by,
            event_id=document.event_id,
            supplier=document.issuer,
            receipt=document,
            created_by=member,
        )
        try:
            check_entry(entry, keeps_member=False)
        except ValidationError as error:
            raise ValidationError(
                {FIELDS.get(field, field): errors for field, errors in error.error_dict.items()}
            ) from error
        document.paid_on = data.paid_on
        _pay(document, member)
        entry.save()
    return documents().get(pk=document.pk)


def attach_invoice(document: Document, data: InvoiceAttachIn, member: User) -> Document:
    """An invoice becomes the receipt of an expense that has none, paid on the
    date of that expense unless it says otherwise.
    """
    with transaction.atomic():
        document = _locked_invoice(document)
        entry = (
            LedgerEntry.objects.select_for_update()
            .filter(pk=data.entry, kind=LedgerEntryKind.EXPENSE, receipt__isnull=True)
            .first()
        )
        if entry is None:
            raise ValidationError({"entry": NOT_AN_OPEN_EXPENSE})
        if document.paid_on is None:
            document.paid_on = entry.date
        _pay(document, member)
        entry.receipt = document
        entry.save(update_fields=["receipt"])
    return documents().get(pk=document.pk)


def unpaid_invoices(today: dt.date) -> QuerySet[Document]:
    """The invoices « à régler »: validated, neither paid nor recorded, those
    taken over from the v1 left aside; by due date, those without one last.
    """
    return (
        Document.objects.filter(
            category=DocumentCategory.INVOICE,
            status=DocumentStatus.VALIDATED,
            paid_on__isnull=True,
            ledger_entry__isnull=True,
        )
        .exclude(source=DocumentSource.V1_IMPORT)
        .annotate(
            # A due date may be missing: compared alone, it would be NULL.
            overdue=Case(
                When(due_date__lt=today, then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            )
        )
        .order_by(F("due_date").asc(nulls_last=True), "pk")
    )


def _locked_invoice(document: Document) -> Document:
    # Locked first, before the entry: two members recording the same invoice at
    # once record it once.
    document = Document.objects.select_for_update().get(pk=document.pk)
    if document.category != DocumentCategory.INVOICE:
        raise ValidationError(NOT_AN_INVOICE)
    if hasattr(document, "ledger_entry"):
        raise ValidationError(HAS_EXPENSE)
    return document


def _pay(document: Document, member: User) -> None:
    if document.status == DocumentStatus.TO_REVIEW:
        mark_validated(document, member)
    document.save()
