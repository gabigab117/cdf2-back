from django.shortcuts import get_object_or_404
from ninja import File, Router, Status, UploadedFile

from core.schemas import REFUSALS, ErrorOut, ValidationErrorOut
from documents.services.files import WEBP
from photos.models import Album, Photo
from photos.schemas import AlbumIn, AlbumOut, PhotoOut, PhotoRendition
from photos.services.photos import create_album, delete_photo, upload_photo, visible_photos
from photos.services.serving import photo_response

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


@router.post(
    "/albums",
    response={201: AlbumOut, 400: ErrorOut, 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="Create an album",
)
def create(request, payload: AlbumIn):
    """Record an album, private until a member publishes it (D17)."""
    return Status(201, create_album(payload))


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


@router.delete(
    "/photos/{photo_id}",
    response={204: None, **REFUSALS},
    summary="Delete a photo",
)
def delete(request, photo_id: int):
    """Delete a photo and its files: also how a removal asked for is done (D17)."""
    delete_photo(get_object_or_404(Photo, pk=photo_id))
    return Status(204, None)


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
