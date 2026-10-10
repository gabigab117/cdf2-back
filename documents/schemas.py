import datetime as dt
from decimal import Decimal

from ninja import Schema

from accounts.schemas import BoardMemberOut
from core.schemas import InputSchema
from documents.models import DocumentCategory, DocumentSource, DocumentStatus


class DocumentUploadIn(InputSchema):
    """How the member who deposits a file classifies it: without the assistant
    (phase 9), the board classifies by hand.
    """

    category: DocumentCategory
    # Left out: the name of the file, without its extension.
    title: str | None = None
    # The id of an event, or none.
    event: int | None = None


class DocumentEventOut(Schema):
    """The event a document belongs to."""

    id: int
    title: str


class DocumentOut(Schema):
    """A document of the board, as its detail panel shows it."""

    id: int
    title: str
    category: DocumentCategory
    status: DocumentStatus
    source: DocumentSource
    original_name: str
    mime_type: str
    # In bytes.
    size: int
    document_date: dt.date | None
    # The date it is listed by: the document's own, or the day it was deposited.
    date: dt.date
    issuer: str
    reference: str
    amount: Decimal | None
    due_date: dt.date | None
    paid_on: dt.date | None
    event: DocumentEventOut | None
    note: str
    # None for a document taken over from the v1, or once the account is deleted.
    uploaded_by: BoardMemberOut | None
    validated_by: BoardMemberOut | None
    validated_at: dt.datetime | None
    created_at: dt.datetime
