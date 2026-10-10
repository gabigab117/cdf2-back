import datetime as dt

from ninja import Schema

from accounts.schemas import BoardMemberOut
from core.schemas import InputSchema
from notes.models import NoteTag


class NoteIn(InputSchema):
    """A note as a member writes it. Its values are checked by the model."""

    # The id of an event, or none for a general note.
    event: int | None
    text: str
    tag: NoteTag | None
    pinned: bool


class NoteUpdateIn(InputSchema):
    """A note or a reply rewritten by its author: a note stays on its event.

    A reply keeps no tag and no pin: it is sent with neither.
    """

    text: str
    tag: NoteTag | None
    pinned: bool


class ReplyIn(InputSchema):
    text: str


class ReplyOut(Schema):
    """A reply to a note, in the order the replies were written."""

    id: int
    # None once the author's account is deleted.
    author: BoardMemberOut | None
    text: str
    created_at: dt.datetime
    updated_at: dt.datetime
    # Whether the member asking wrote it, and may thus rewrite or delete it.
    editable: bool


class NoteOut(ReplyOut):
    """A note of the board, with its replies."""

    tag: NoteTag | None
    pinned: bool
    replies: list[ReplyOut]
