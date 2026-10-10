import datetime as dt
from decimal import Decimal
from typing import Annotated

from ninja import Field, FilterLookup, FilterSchema, Schema

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


class ExtractedTaskIn(InputSchema):
    """A task the minutes of a meeting list, to create when they are validated."""

    title: str
    # The id of a board member, or none.
    assignee: int | None


class DocumentExtractedIn(InputSchema):
    """What belongs to one kind of document, whole, every key required: the
    service keeps the keys of the document's category.
    """

    # An order: when it is to be delivered, and what it holds, in a few words.
    delivery_date: dt.date | None
    items: str
    # The minutes of a meeting, or any other paper: what it says.
    abstract: str
    # The minutes: what was decided, and the tasks to create.
    decisions: list[str]
    tasks: list[ExtractedTaskIn]
    # Any other paper: a date it tells, as it tells it.
    key_date: str


class DocumentIn(InputSchema):
    """A document as a member corrects it: whole, every key required.

    Its values are checked by the model, whose messages are in French.
    """

    category: DocumentCategory
    title: str
    # The id of an event, or none.
    event: int | None
    document_date: dt.date | None
    issuer: str
    reference: str
    amount: Decimal | None
    due_date: dt.date | None
    paid_on: dt.date | None
    note: str
    extracted: DocumentExtractedIn


class DocumentFilters(FilterSchema):
    """The documents a search keeps: every filter given applies."""

    # Any word of the document: its title, issuer, number, remark or file name,
    # its amount as the board writes it (« 380,00 »), the title of its event, or
    # the texts typed for its kind.
    search: Annotated[
        str | None,
        FilterLookup(
            [
                "title__icontains",
                "issuer__icontains",
                "reference__icontains",
                "note__icontains",
                "original_name__icontains",
                "amount_text__icontains",
                "event__title__icontains",
                "extracted__abstract__icontains",
                "extracted__decisions__icontains",
                "extracted__items__icontains",
                "extracted__key_date__icontains",
            ]
        ),
    ] = None
    status: DocumentStatus | None = None
    event: int | None = None


class DocumentListFilters(DocumentFilters):
    """The filters of the list, which also keeps a single category."""

    category: DocumentCategory | None = None


class DocumentEventOut(Schema):
    """The event a document belongs to."""

    id: int
    title: str


class DocumentItemOut(Schema):
    """A document as the list shows it."""

    id: int
    title: str
    category: DocumentCategory
    status: DocumentStatus
    event: DocumentEventOut | None
    amount: Decimal | None
    # The date it is listed by: the document's own, or the day it was deposited.
    date: dt.date


class DocumentCountsOut(Schema):
    """How many documents answer a search, in all and by category, whatever
    the category shown: the chips of the list.
    """

    total: int
    invoice: int
    order: int
    minutes: int
    misc: int


class ExtractedTaskOut(Schema):
    title: str
    # The id of the board member it is to be assigned to, or none.
    assignee: int | None = None


class DocumentExtractedOut(Schema):
    """What belongs to the document's kind: a key of another kind is left empty."""

    delivery_date: dt.date | None = None
    items: str = ""
    abstract: str = ""
    decisions: list[str] = Field(default_factory=list)
    tasks: list[ExtractedTaskOut] = Field(default_factory=list)
    key_date: str = ""


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
    extracted: DocumentExtractedOut
    note: str
    # None for a document taken over from the v1, or once the account is deleted.
    uploaded_by: BoardMemberOut | None
    validated_by: BoardMemberOut | None
    validated_at: dt.datetime | None
    created_at: dt.datetime
