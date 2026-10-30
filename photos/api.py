from django.shortcuts import get_object_or_404
from ninja import File, Query, Router, Status, UploadedFile
from ninja.pagination import paginate

from core.schemas import REFUSALS, ErrorOut, ValidationErrorOut
from documents.services.files import WEBP
from events.models import Event
from photos.models import Album, Photo
from photos.schemas import (
    AlbumFilters,
    AlbumIn,
    AlbumItemOut,
    AlbumOut,
    AlbumPublicationIn,
    CoverIn,
    EventCoverOut,
    HiddenIn,
    ImageRightsIn,
    PhotoOut,
    PhotoRendition,
    PhotoSelectionIn,
)
from photos.services.covers import event_cover, set_event_cover
from photos.services.photos import (
    albums,
    albums_with_photos,
    create_album,
    delete_album,
    delete_photos,
    publish_album,
    selected_photos,
    set_album_cover,
    set_hidden,
    set_image_rights_to_review,
    update_album,
    upload_photo,
    visible_photos,
)
from photos.services.serving import ZIP, photo_response, zip_response

router = Router(tags=["photos"])

# The site's operations, open to anyone: each declares auth=None.
public_router = Router(tags=["site"])

# A photo's file is not JSON: the operation returns it as it is, and declares
# its content here. Every size is a WebP.
PHOTO_FILE = {
    "responses": {
        200: {
            "description": "The photo, in the size asked for",
            "content": {WEBP: {"schema": {"type": "string", "format": "binary"}}},
        }
    }
}

# Nor is the zip of a selection's images.
ZIP_FILE = {
    "responses": {
        200: {
            "description": "The zip of the selected photos' images",
            "content": {ZIP: {"schema": {"type": "string", "format": "binary"}}},
        }
    }
}


def _album(album_id: int) -> Album:
    return get_object_or_404(albums_with_photos(), pk=album_id)


@router.get(
    "/albums",
    response={200: list[AlbumItemOut], 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="List the albums",
)
@paginate
def list_albums(request, filters: Query[AlbumFilters]):
    """The albums, by page, the latest first: those of an event, when one is given."""
    return filters.filter(albums())


@router.post(
    "/albums",
    response={201: AlbumOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="Create an album",
)
def create(request, payload: AlbumIn):
    """Record an album, private until a member publishes it (D17)."""
    return Status(201, _album(create_album(payload).pk))


@router.get("/albums/{album_id}", response={200: AlbumOut, **REFUSALS}, summary="Read an album")
def read(request, album_id: int):
    """An album and every photo of it: 300 at most."""
    return _album(album_id)


@router.put(
    "/albums/{album_id}",
    response={200: AlbumOut, 400: ErrorOut, **REFUSALS},
    summary="Update an album",
)
def update(request, album_id: int, payload: AlbumIn):
    update_album(get_object_or_404(Album, pk=album_id), payload)
    return _album(album_id)


@router.put(
    "/albums/{album_id}/published",
    response={200: AlbumOut, 400: ErrorOut, **REFUSALS},
    summary="Publish an album, or take it off the site",
)
def publish(request, album_id: int, payload: AlbumPublicationIn):
    """Show the album's visible photos on the site, or take them all off it (D17)."""
    publish_album(get_object_or_404(Album, pk=album_id), payload.published)
    return _album(album_id)


@router.put(
    "/albums/{album_id}/cover",
    response={200: AlbumOut, 400: ErrorOut, **REFUSALS},
    summary="Choose an album's cover",
)
def cover(request, album_id: int, payload: CoverIn):
    """One of the album's photos, or none."""
    set_album_cover(get_object_or_404(Album, pk=album_id), payload.cover)
    return _album(album_id)


@router.delete("/albums/{album_id}", response={204: None, **REFUSALS}, summary="Delete an album")
def delete(request, album_id: int):
    """Delete an album, its photos and their files."""
    delete_album(get_object_or_404(Album, pk=album_id))
    return Status(204, None)


@router.post(
    "/albums/{album_id}/photos",
    response={201: PhotoOut, 400: ErrorOut, **REFUSALS},
    summary="Add a photo to an album",
)
def upload(request, album_id: int, file: File[UploadedFile]):
    """Record a photo, sent alone: an album of many photos is sent one at a time.

    Its type is read from its content; it is kept in WebP, without its
    metadata, in three sizes.
    """
    return Status(201, upload_photo(get_object_or_404(Album, pk=album_id), file, request.auth))


@router.get(
    "/photos/{photo_id}/{rendition}",
    response={200: None, **REFUSALS},
    openapi_extra=PHOTO_FILE,
    summary="Read a photo",
)
def read_file(request, photo_id: int, rendition: PhotoRendition):
    """A size of any photo, published or not."""
    return photo_response(get_object_or_404(Photo, pk=photo_id), rendition, public=False)


@router.put(
    "/albums/{album_id}/photos/hidden",
    response={204: None, 400: ErrorOut, **REFUSALS},
    summary="Hide photos from the site, or show them again",
)
def hide(request, album_id: int, payload: HiddenIn):
    set_hidden(get_object_or_404(Album, pk=album_id), payload.photos, payload.hidden)
    return Status(204, None)


@router.put(
    "/albums/{album_id}/photos/image-rights-to-review",
    response={204: None, 400: ErrorOut, **REFUSALS},
    summary="Hold photos until their image rights are checked, or release them",
)
def review_image_rights(request, album_id: int, payload: ImageRightsIn):
    """A photo to review is kept off the site, whatever its album (D17)."""
    set_image_rights_to_review(
        get_object_or_404(Album, pk=album_id), payload.photos, payload.image_rights_to_review
    )
    return Status(204, None)


@router.post(
    "/albums/{album_id}/photos/delete",
    response={204: None, 400: ErrorOut, **REFUSALS},
    summary="Delete photos",
)
def delete_selection(request, album_id: int, payload: PhotoSelectionIn):
    """Delete the selected photos and their files: also how a removal asked for is
    done (D17).
    """
    delete_photos(get_object_or_404(Album, pk=album_id), payload.photos)
    return Status(204, None)


@router.post(
    "/albums/{album_id}/photos/zip",
    response={200: None, 400: ErrorOut, **REFUSALS},
    openapi_extra=ZIP_FILE,
    summary="Download photos",
)
def download(request, album_id: int, payload: PhotoSelectionIn):
    """The zip of the selected photos' images, under the album's title. The
    selection is read before the zip starts: a refusal is still a 422.
    """
    album = get_object_or_404(Album, pk=album_id)
    return zip_response(album, list(selected_photos(album, payload.photos)))


@router.get(
    "/events/{event_id}/cover",
    response={200: EventCoverOut, **REFUSALS},
    summary="Read an event's cover",
)
def read_event_cover(request, event_id: int):
    """The cover of an event, and the albums it is chosen from (D17)."""
    return event_cover(get_object_or_404(Event, pk=event_id))


@router.put(
    "/events/{event_id}/cover",
    response={200: EventCoverOut, 400: ErrorOut, **REFUSALS},
    summary="Choose an event's cover",
)
def choose_event_cover(request, event_id: int, payload: CoverIn):
    """A photo of the event's albums or of its previous edition's, or none. Only this
    operation sets it, never the event's.
    """
    return set_event_cover(get_object_or_404(Event, pk=event_id), payload.cover)


@public_router.get(
    "/photos/{photo_id}/{rendition}",
    auth=None,
    response={200: None, 404: ErrorOut, 422: ValidationErrorOut},
    openapi_extra=PHOTO_FILE,
    summary="Read a visible photo",
)
def public_file(request, photo_id: int, rendition: PhotoRendition):
    """A size of a photo the site shows (D17): any other is not found."""
    return photo_response(get_object_or_404(visible_photos(), pk=photo_id), rendition, public=True)
