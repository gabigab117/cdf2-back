"""A photo as the server keeps it: in WebP, without its metadata (D9), in three sizes.

The file sent is decoded once, into the image; each smaller size is made from
the one above it.
"""

import datetime as dt
from dataclasses import dataclass
from io import BytesIO
from typing import ClassVar

from django.conf import settings
from django.core.files.base import ContentFile, File
from django.utils import timezone
from imagekit.processors import ResizeToFit
from PIL import ExifTags, Image

from documents.services.files import (
    WebpPhoto,
    generate,
    read_file,
    read_image_header,
    renamed,
    to_webp,
)

NOT_A_PHOTO = "Type de fichier non accepté : déposez une photo (JPEG, PNG, HEIC, WebP)."

# The longest side of the viewer's photo, and of the grid's.
DISPLAY_SIDE = 2048
THUMBNAIL_SIDE = 640


class WebpDisplay(WebpPhoto):
    """The photo the viewer shows, made from the image, already upright."""

    processors: ClassVar[list[object]] = [ResizeToFit(DISPLAY_SIDE, DISPLAY_SIDE, upscale=False)]


class WebpThumbnail(WebpPhoto):
    """The photo a grid shows, made from the display."""

    processors: ClassVar[list[object]] = [
        ResizeToFit(THUMBNAIL_SIDE, THUMBNAIL_SIDE, upscale=False)
    ]


@dataclass(frozen=True)
class StoredPhoto:
    """A photo ready to store, in its three sizes, with what is recorded of it."""

    image: ContentFile
    display: ContentFile
    thumbnail: ContentFile
    name: str
    sha256: str
    width: int
    height: int
    taken_at: dt.datetime | None


def read_photo(file: File) -> StoredPhoto:
    """An uploaded photo ready to store.

    Every refusal is located on the file: empty, too large, not an image of an
    accepted type, of too many pixels, or unreadable.
    """
    upload = read_file(file, settings.PHOTO_MAX_SIZE)
    header = read_image_header(upload.data, NOT_A_PHOTO)
    # A PNG's image keeps its pixels, as a document does; its smaller sizes
    # need not.
    image = to_webp(upload.data, header)
    display = generate(WebpDisplay, image)
    with Image.open(BytesIO(image)) as opened:
        width, height = opened.size
    return StoredPhoto(
        image=ContentFile(image),
        display=ContentFile(display),
        thumbnail=ContentFile(generate(WebpThumbnail, display)),
        name=renamed(upload.name, ".webp"),
        sha256=upload.sha256,
        width=width,
        height=height,
        taken_at=_taken_at(header.exif),
    )


def _taken_at(exif: Image.Exif) -> dt.datetime | None:
    # Read before the metadata is dropped. A camera records the time of the
    # place it is in, without a zone: the committee's photos are taken in Paris
    # time.
    taken = exif.get_ifd(ExifTags.IFD.Exif).get(ExifTags.Base.DateTimeOriginal)
    try:
        return timezone.make_aware(dt.datetime.strptime(taken, "%Y:%m:%d %H:%M:%S"))
    except (TypeError, ValueError):
        return None
