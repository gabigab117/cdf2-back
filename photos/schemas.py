import datetime as dt
from enum import StrEnum

from ninja import FilterSchema, Schema

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


class AlbumFilters(FilterSchema):
    """The albums a list keeps: those of an event, when one is given."""

    event: int | None = None


class AlbumPublicationIn(InputSchema):
    # True: the site shows its visible photos (D17).
    published: bool


class CoverIn(InputSchema):
    """The cover of an album, or of an event: the id of a photo, or none."""

    cover: int | None


class PhotoSelectionIn(InputSchema):
    """The photos of an album a member selected in its grid."""

    photos: list[int]


class HiddenIn(PhotoSelectionIn):
    hidden: bool


class ImageRightsIn(PhotoSelectionIn):
    image_rights_to_review: bool


class AlbumItemOut(Schema):
    """An album of the board's list."""

    id: int
    title: str
    date: dt.date
    event: AlbumEventOut | None
    published: bool
    # The id of its cover photo, or none.
    cover: int | None
    photos_count: int

    @staticmethod
    def resolve_cover(album):
        return album.cover_id


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


class AlbumOut(AlbumItemOut):
    """An album of the board, with every photo of it: an album holds 300 at most."""

    # The members who added its photos, accounts deleted since left out.
    contributors_count: int
    created_at: dt.datetime
    # In the order they were taken, those without a date last, then as added.
    photos: list[PhotoOut]


class EventCoverOut(Schema):
    """The cover of an event, and the albums it is chosen from: the event's and its
    previous edition's, the latest first (D17).
    """

    # The id of its photo, or none.
    cover: int | None
    # Whether the site shows it: its photo is visible.
    visible: bool
    albums: list[AlbumItemOut]
