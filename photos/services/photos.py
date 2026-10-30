"""The committee's albums and their photos (D17): private until a member publishes an
album, and shown on the site only while visible.
"""

from collections.abc import Iterable

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.files.base import File
from django.db import transaction
from django.db.models import Count, F, OuterRef, Prefetch, QuerySet, Subquery
from django.db.models.fields.files import FieldFile

from accounts.models import User
from photos.models import Album, Photo
from photos.schemas import AlbumIn
from photos.services.images import read_photo

# An album is seen whole, in a single grid, and its selection covers it all: it
# holds this many photos at most (D17, card 8.3).
MAX_ALBUM_PHOTOS = 300

# The order of the albums, on the board as on the site: the latest first.
ALBUM_ORDER = ("-date", "-created_at", "-pk")

# The order of an album's photos: as they were taken, those without a date last,
# then as they were added.
PHOTO_ORDER = (F("taken_at").asc(nulls_last=True), "created_at", "pk")


def visible_photos() -> QuerySet[Photo]:
    """The photos the site may show: of a published album, neither hidden nor
    awaiting a check of their image rights (D17).

    The single rule of every public reading: a photo's file, the lists and the
    covers.
    """
    return Photo.objects.filter(album__published=True, hidden=False, image_rights_to_review=False)


def visible_cover() -> Subquery:
    """The id of a cover, an album's or an event's, while the site may show its
    photo; null otherwise. An expression, to annotate a list with.
    """
    return Subquery(visible_photos().filter(pk=OuterRef("cover")).values("pk"))


def albums() -> QuerySet[Album]:
    """The albums of the board, the latest first, with their event and their number
    of photos.
    """
    return (
        Album.objects.select_related("event")
        .annotate(photos_count=Count("photos"))
        .order_by(*ALBUM_ORDER)
    )


def albums_with_photos() -> QuerySet[Album]:
    """The albums with every photo of theirs, in order, and the number of members
    who added them.
    """
    photos = Photo.objects.select_related("uploaded_by").order_by(*PHOTO_ORDER)
    return (
        albums()
        .annotate(contributors_count=Count("photos__uploaded_by", distinct=True))
        .prefetch_related(Prefetch("photos", queryset=photos))
    )


def create_album(data: AlbumIn) -> Album:
    """Record an album, private until a member publishes it."""
    return _save(Album(), data)


def update_album(album: Album, data: AlbumIn) -> Album:
    """Correct an album's title, date or event."""
    return _save(album, data)


def publish_album(album: Album, published: bool) -> None:
    """Show an album's visible photos on the site, or take them all off it at once."""
    album.published = published
    album.save(update_fields=["published"])


def set_album_cover(album: Album, cover: int | None) -> None:
    """Choose one of an album's photos as its cover, or none."""
    # The choice depends on the album: no limit_choices_to can name it.
    if cover is not None and not album.photos.filter(pk=cover).exists():
        raise ValidationError({"cover": "Choisissez une photo de l’album."})
    album.cover_id = cover
    album.save(update_fields=["cover"])


def delete_album(album: Album) -> None:
    """Delete an album, its photos and, once that is done, their files."""
    _delete(album, album.photos.all())


def upload_photo(album: Album, file: File, member: User | None) -> Photo:
    """Record the photo a member adds to an album, in its three sizes. The file is
    refused before the photo's fields, and before it is read when the album is full.
    """
    if album.photos.count() >= MAX_ALBUM_PHOTOS:
        raise ValidationError(
            {"file": f"Un album compte {MAX_ALBUM_PHOTOS} photos au plus : créez-en un second."}
        )
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


def selected_photos(album: Album, ids: list[int]) -> QuerySet[Photo]:
    """The photos of an album a member selected, in the album's order: there is
    one at least, and each is of it.
    """
    selection = album.photos.filter(pk__in=ids).order_by(*PHOTO_ORDER)
    if not ids or selection.count() != len(set(ids)):
        raise ValidationError({"photos": "Choisissez des photos de l’album."})
    return selection


def set_hidden(album: Album, ids: list[int], hidden: bool) -> None:
    """Hide the selected photos from the site, or show them again."""
    selected_photos(album, ids).update(hidden=hidden)


def set_image_rights_to_review(album: Album, ids: list[int], to_review: bool) -> None:
    """Hold the selected photos off the site until their image rights are checked,
    or release them (D17).
    """
    selected_photos(album, ids).update(image_rights_to_review=to_review)


def delete_photos(album: Album, ids: list[int]) -> None:
    """Delete the selected photos and, once that is done, their three files: by a
    member's choice, or because the person on one asked for its removal (D17). An
    album or an event whose cover one was has none left.
    """
    selection = selected_photos(album, ids)
    _delete(selection, selection)


def _save(album: Album, data: AlbumIn) -> Album:
    album.title = data.title
    album.date = data.date
    album.event_id = data.event
    album.full_clean()
    album.save()
    return album


def _delete(target: Album | QuerySet[Photo], photos: Iterable[Photo]) -> None:
    with transaction.atomic():
        files = [file for photo in photos for file in _files(photo)]
        target.delete()
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
