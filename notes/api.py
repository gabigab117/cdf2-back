from django.shortcuts import get_object_or_404
from ninja import Router, Status
from ninja.pagination import paginate

from core.schemas import REFUSALS, ErrorOut, ValidationErrorOut
from notes.schemas import NoteIn, NoteOut, NoteUpdateIn, ReplyIn, ReplyOut
from notes.services.notes import (
    create_note,
    delete_note,
    event_notes,
    notes_to_reply_to,
    notes_written_by,
    reply,
    update_note,
)

router = Router(tags=["notes"])


@router.get(
    "/notes",
    response={200: list[NoteOut], 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="List the notes of an event",
)
@paginate
def list_notes(request, event: int):
    """The notes of an event, by page: the pinned ones first, then the latest,
    each with its replies.
    """
    return event_notes(request.auth, event)


# Declared before the operations on /notes/{note_id}: Ninja tries the paths in
# their order, and the id would take "general" for itself, then answer 405.
@router.get(
    "/notes/general",
    response={200: list[NoteOut], 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="List the general notes",
)
@paginate
def list_general_notes(request):
    """The notes without an event (A11), by page, in the same order as an
    event's, each with its replies.
    """
    return event_notes(request.auth, None)


@router.post(
    "/notes",
    response={
        201: NoteOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Write a note",
)
def create(request, payload: NoteIn):
    """Record a note of the signed-in member, on an event or general."""
    return Status(201, create_note(payload, request.auth))


@router.put(
    "/notes/{note_id}",
    response={200: NoteOut, 400: ErrorOut, **REFUSALS},
    summary="Rewrite a note",
)
def update(request, note_id: int, payload: NoteUpdateIn):
    """Rewrite a note or a reply. Only its author finds it: anyone else gets a 404."""
    return update_note(get_object_or_404(notes_written_by(request.auth), pk=note_id), payload)


@router.delete(
    "/notes/{note_id}",
    response={204: None, **REFUSALS},
    summary="Delete a note",
)
def delete(request, note_id: int):
    """Delete a note with its replies, or a reply. Only its author finds it."""
    delete_note(get_object_or_404(notes_written_by(request.auth), pk=note_id))
    return Status(204, None)


@router.post(
    "/notes/{note_id}/replies",
    response={201: ReplyOut, 400: ErrorOut, **REFUSALS},
    summary="Reply to a note",
)
def create_reply(request, note_id: int, payload: ReplyIn):
    """Record a reply of the signed-in member. A reply cannot be answered: 404."""
    note = get_object_or_404(notes_to_reply_to(), pk=note_id)
    return Status(201, reply(note, payload, request.auth))
