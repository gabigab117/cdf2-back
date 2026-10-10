"""The board's notes: on an event or general, with one level of replies (A11).

Only its author rewrites or deletes a note or a reply. Anyone else does not
find it: the operations look it up among the notes the member wrote.
"""

from django.db.models import BooleanField, Case, Prefetch, QuerySet, Value, When

from accounts.models import User
from notes.models import Note
from notes.schemas import NoteIn, NoteUpdateIn, ReplyIn


def member_notes(member: User) -> QuerySet[Note]:
    """The notes as a member reads them, with their authors and their replies,
    the oldest reply first. Each note and reply tells whether the member wrote it.
    """
    replies = (
        Note.objects.select_related("author")
        .annotate(editable=_written_by(member))
        .order_by("created_at", "pk")
    )
    return (
        Note.objects.select_related("author", "document")
        .annotate(editable=_written_by(member))
        .prefetch_related(Prefetch("replies", queryset=replies))
    )


def event_notes(member: User, event_id: int) -> QuerySet[Note]:
    """The notes of an event, replies aside: the pinned ones first, then the latest."""
    return member_notes(member).filter(event_id=event_id).order_by("-pinned", "-created_at", "-pk")


def notes_written_by(member: User) -> QuerySet[Note]:
    """The notes and replies a member may rewrite or delete: their own."""
    return Note.objects.filter(author=member)


def notes_to_reply_to() -> QuerySet[Note]:
    """The notes a reply may answer: replies stay one level deep."""
    return Note.objects.filter(parent__isnull=True)


def create_note(data: NoteIn, author: User) -> Note:
    """Record a note of a member, on an event or general, with its attachment if any."""
    note = Note(
        event_id=data.event,
        author=author,
        text=data.text,
        tag=data.tag,
        pinned=data.pinned,
        document_id=data.document,
    )
    return _save(note, author)


def update_note(note: Note, data: NoteUpdateIn) -> Note:
    """Rewrite a note or a reply, by its author."""
    note.text = data.text
    note.tag = data.tag
    note.pinned = data.pinned
    return _save(note, note.author)


def reply(note: Note, data: ReplyIn, author: User) -> Note:
    """Record a member's reply to a note."""
    return _save(Note(parent=note, author=author, text=data.text), author)


def delete_note(note: Note) -> None:
    """Delete a note, with its replies, or a reply alone."""
    note.delete()


def _save(note: Note, member: User) -> Note:
    note.full_clean()
    note.save()
    # Read again as its author reads it: the answer tells it may be changed,
    # and holds its replies.
    return member_notes(member).get(pk=note.pk)


def _written_by(member: User) -> Case:
    # A plain comparison of the author would be NULL, not false, for a note
    # whose author's account was deleted.
    return Case(
        When(author=member, then=Value(True)), default=Value(False), output_field=BooleanField()
    )
