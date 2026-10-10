"""The committee's documents: deposited by the board, classified when they arrive,
then reviewed (A8).
"""

from pathlib import PurePath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import File
from django.db import transaction
from django.db.models import QuerySet
from django.db.models.functions import Coalesce, TruncDate

from accounts.models import User
from documents.models import Document
from documents.schemas import DocumentUploadIn
from documents.services.files import read_upload


def documents() -> QuerySet[Document]:
    """The documents as the board reads them, with their event and their people.

    Each is dated by its own date, or else by the day it was deposited, in
    Paris time: the list is ordered by it, and shows it.
    """
    return Document.objects.select_related("event", "uploaded_by", "validated_by").annotate(
        date=Coalesce("document_date", TruncDate("created_at"))
    )


def upload_document(file: File, data: DocumentUploadIn, member: User) -> Document:
    """Record the file a member deposits, as they classify it: it awaits review."""
    stored = read_upload(file, max_size=settings.DOCUMENT_MAX_SIZE)
    document = Document(
        category=data.category,
        title=data.title or PurePath(file.name).stem[:200],
        event_id=data.event,
        original_name=stored.name,
        mime_type=stored.mime_type,
        size=stored.size,
        sha256=stored.sha256,
        uploaded_by=member,
    )
    _check(document)
    # Written once checked, so that a refused document leaves no file; and
    # removed when the record fails, so that none is left without one.
    document.file.save(stored.name, stored.content, save=False)
    try:
        with transaction.atomic():
            document.save()
    except BaseException:
        document.file.delete(save=False)
        raise
    return documents().get(pk=document.pk)


def _check(document: Document) -> None:
    try:
        document.full_clean(exclude={"file"})
    except ValidationError as error:
        # The same file deposited twice is told on the file the member chose,
        # not on its fingerprint.
        raise ValidationError(
            {
                ("file" if field == "sha256" else field): messages
                for field, messages in error.error_dict.items()
            }
        ) from error
