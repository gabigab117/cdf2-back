import datetime as dt
from enum import StrEnum

from ninja import Schema

from accounts.schemas import BoardMemberOut
from core.schemas import InputSchema


# Named after their model rather than nested in it: the OpenAPI document names an
# enumeration after its class (see events/models.py).
class PhotoRendition(StrEnum):
    """A size of a photo smaller than its image, named after its field."""

    THUMBNAIL = "thumbnail"
    DISPLAY = "display"


class AlbumIn(InputSchema):
    """An album as a member creates it: private until it is published (D17).

    Its values are checked by the model, whose messages are in French.
    """

    title: str
    date: dt.date
    # The id of an event, or none.
    event: int | None


class AlbumEventOut(Schema):
    """The event an album belongs to."""

    id: int
    title: str


class AlbumOut(Schema):
    """An album of the board."""

    id: int
    title: str
    date: dt.date
    event: AlbumEventOut | None
    published: bool
    created_at: dt.datetime


class PhotoOut(Schema):
    """A photo of an album, as the board sees it."""

    id: int
    original_name: str
    # Of its image: the smaller sizes keep its proportions.
    width: int
    height: int
    taken_at: dt.datetime | None
    hidden: bool
    image_rights_to_review: bool
    # None once the account is deleted.
    uploaded_by: BoardMemberOut | None
    created_at: dt.datetime
