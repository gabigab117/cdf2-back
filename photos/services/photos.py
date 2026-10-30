"""The committee's albums and their photos (D17): private until a member publishes an
album, and shown on the site only while visible.
"""

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.files.base import File
from django.db import transaction
from django.db.models import QuerySet
from django.db.models.fields.files import FieldFile

from accounts.models import User
from photos.models import Album, Photo
from photos.schemas import AlbumIn
from photos.services.images import read_photo


def visible_photos() -> QuerySet[Photo]:
    """The photos the site may show: of a published album, neither hidden nor
    awaiting a check of their image rights (D17).

    The single rule of every public reading: a photo's file, the lists and the
    covers.
    """
    return Photo.objects.filter(album__published=True, hidden=False, image_rights_to_review=False)


def create_album(data: AlbumIn) -> Album:
    """Record an album, private until a member publishes it."""
    album = Album(title=data.title, date=data.date, event_id=data.event)
    album.full_clean()
    album.save()
    return album


def upload_photo(album: Album, file: File, member: User) -> Photo:
    """Record the photo a member adds to an album, in its three sizes. The file is
    refused before the photo's fields.
    """
    stored = read_photo(file)
    photo = Photo(
        album=album,
        original_name=stored.name,
        sha256=stored.sha256,
        width=stored.width,
        height=stored.height,
        taken_at=stored.taken_at,
        uploaded_by=member,
    )
    _check(photo)
    # Written once checked, so that a refused photo leaves no file; and removed
    # when the record fails, so that none is left without one.
    photo.image.save(stored.name, stored.image, save=False)
    photo.display.save(stored.name, stored.display, save=False)
    photo.thumbnail.save(stored.name, stored.thumbnail, save=False)
    try:
        photo.save()
    except BaseException:
        _delete_files(_files(photo))
        raise
    return photo


def delete_photo(photo: Photo) -> None:
    """Delete a photo and, once that is done, its three files: by a member's
    choice, or because the person on it asked for its removal (D17). An album
    whose cover it was has none left.
    """
    files = _files(photo)
    with transaction.atomic():
        photo.delete()
        transaction.on_commit(lambda: _delete_files(files))


def _check(photo: Photo) -> None:
    try:
        photo.full_clean(exclude={"image", "display", "thumbnail"})
    except ValidationError as error:
        # The same file added twice to an album is told on the file the member
        # chose, not on the photo.
        raise ValidationError(
            {
                ("file" if field == NON_FIELD_ERRORS else field): messages
                for field, messages in error.error_dict.items()
            }
        ) from error


def _files(photo: Photo) -> list[FieldFile]:
    return [photo.image, photo.display, photo.thumbnail]


def _delete_files(files: list[FieldFile]) -> None:
    for file in files:
        file.storage.delete(file.name)
