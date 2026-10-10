"""The committee's documents: deposited by the board, classified when they arrive,
then reviewed (A8).

A document awaits review until a member validates it. The minutes of a meeting
then create the tasks they list: on their event, or general tasks (D10).
"""

from pathlib import PurePath

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.base import File
from django.db import transaction
from django.db.models import CharField, Count, Q, QuerySet, Value
from django.db.models.functions import Cast, Coalesce, Replace, TruncDate
from django.utils import timezone

from accounts.models import User
from documents.models import Document, DocumentCategory, DocumentStatus
from documents.schemas import DocumentIn, DocumentUploadIn
from documents.services.files import read_upload
from tasks.models import Task
from tasks.schemas import TaskIn
from tasks.services.tasks import create_task

# What belongs to each kind of document, among the keys of its extracted data.
EXTRACTED_KEYS = {
    DocumentCategory.INVOICE: (),
    DocumentCategory.ORDER: ("delivery_date", "items"),
    DocumentCategory.MINUTES: ("abstract", "decisions", "tasks"),
    DocumentCategory.MISC: ("abstract", "key_date"),
}


def documents() -> QuerySet[Document]:
    """The documents as the board reads them, with their event and their people.

    Each is dated by its own date, or else by the day it was deposited, in
    Paris time: the list is ordered by it, and shows it.
    """
    return Document.objects.select_related("event", "uploaded_by", "validated_by").annotate(
        date=Coalesce("document_date", TruncDate("created_at"))
    )


def listed_documents() -> QuerySet[Document]:
    """The documents in the order of the list, the latest date first, each with
    its amount as the board writes it (« 380,00 »), for the search.
    """
    amount_text = Replace(Cast("amount", output_field=CharField()), Value("."), Value(","))
    return documents().annotate(amount_text=amount_text).order_by("-date", "-created_at", "-pk")


def document_counts(selection: QuerySet[Document]) -> dict[str, int]:
    """How many documents a selection holds, in all and by category."""
    by_category = {
        category: Count("pk", filter=Q(category=category)) for category in DocumentCategory.values
    }
    return selection.aggregate(total=Count("pk"), **by_category)


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


def update_document(document: Document, data: DocumentIn) -> Document:
    """Correct a document whole: how it is classified, its fields, and what
    belongs to its kind. A validated document stays validated.
    """
    document.category = data.category
    document.title = data.title
    document.event_id = data.event
    document.document_date = data.document_date
    document.issuer = data.issuer
    document.reference = data.reference
    document.amount = data.amount
    document.due_date = data.due_date
    document.paid_on = data.paid_on
    document.note = data.note
    extracted = data.extracted.model_dump(mode="json")
    document.extracted = {key: extracted[key] for key in EXTRACTED_KEYS[data.category]}
    document.full_clean()
    for index, task in enumerate(document.extracted.get("tasks", [])):
        _check_task(index, Task(title=task["title"], assignee_id=task["assignee"]))
    document.save()
    return documents().get(pk=document.pk)


def validate_document(document: Document, member: User) -> Document:
    """Validate a document awaiting review, by a member: minutes create the tasks
    they list, on their event, or general without one.
    """
    with transaction.atomic():
        # Locked: two members validating at once create the tasks once.
        document = Document.objects.select_for_update().get(pk=document.pk)
        if document.status == DocumentStatus.VALIDATED:
            raise ValidationError("Ce document est déjà validé.")
        if document.category == DocumentCategory.MINUTES:
            _create_tasks(document, member)
        document.status = DocumentStatus.VALIDATED
        document.validated_by = member
        document.validated_at = timezone.now()
        document.save()
    return documents().get(pk=document.pk)


def delete_document(document: Document) -> None:
    """Delete a document and, once that is done, its file. A note that held it
    as its attachment keeps its text.
    """
    file = document.file
    with transaction.atomic():
        document.delete()
        transaction.on_commit(lambda: file.storage.delete(file.name))


def _create_tasks(document: Document, member: User) -> None:
    for index, task in enumerate(document.extracted.get("tasks", [])):
        data = TaskIn(
            event=document.event_id,
            title=task["title"],
            assignee=task["assignee"],
            due_date=None,
            done=False,
        )
        try:
            create_task(data, member)
        except ValidationError as error:
            raise _task_error(index, error) from error


def _check_task(index: int, task: Task) -> None:
    # The tasks of the minutes are checked as tasks as soon as they are written,
    # not only when the minutes are validated.
    try:
        task.full_clean(exclude={"event", "created_by"})
    except ValidationError as error:
        raise _task_error(index, error) from error


def _task_error(index: int, error: ValidationError) -> ValidationError:
    # Located like a field of a list's item: "extracted.tasks.2.title".
    return ValidationError(
        {
            f"extracted.tasks.{index}.{field}": messages
            for field, messages in error.error_dict.items()
        }
    )


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
