"""The receipt of an entry: the document that proves it (6.2).

A receipt joined from the treasury is filed among the documents, validated as
it arrives: its fields come from the entry the member has just written
(decision of 16/10/2026). Like any deposit, it is told by email (D7).
"""

from django.core.files.base import File

from accounts.models import User
from documents.models import Document, DocumentCategory
from documents.services.documents import deposit_document, mark_validated
from treasury.models import LedgerEntry, LedgerEntryKind


def receipt_document(entry: LedgerEntry, file: File, member: User) -> Document:
    """File the receipt of an entry: an invoice paid on the entry's date for an
    expense, a document « Divers » for an income, such as the letter of a grant.
    """
    expense = entry.kind == LedgerEntryKind.EXPENSE
    document = Document(
        category=DocumentCategory.INVOICE if expense else DocumentCategory.MISC,
        title=entry.label,
        event_id=entry.event_id,
        document_date=entry.date,
        issuer=entry.supplier,
        amount=entry.amount,
        paid_on=entry.date if expense else None,
    )
    mark_validated(document, member)
    return deposit_document(document, file, member)
