"""What a deposited file holds, recognised by its content, never by its name (A8).

A PDF is kept as it is. Any accepted image is converted to WebP (D9): turned
upright, reduced to 4,000 px at most, and stripped of its metadata, the place a
photo was taken among them.
"""

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile, File
from imagekit import ImageSpec
from imagekit.processors import ResizeToFit
from PIL import Image, ImageOps, UnidentifiedImageError

PDF = "application/pdf"
WEBP = "image/webp"

# The header every PDF opens with (ISO 32000-1, 7.5.2), checked here: Python
# reads no file type from a content since imghdr was removed (3.13), and Pillow
# reads no PDF.
PDF_SIGNATURE = b"%PDF-"

# The images accepted, as Pillow names their formats: HEIF is the HEIC of an
# iPhone, opened through pillow-heif (documents/apps.py).
IMAGE_FORMATS = ("JPEG", "PNG", "HEIF", "WEBP")

# A larger image would not fit in the memory of the API's workers.
MAX_PIXELS = 50_000_000
# The longest side kept: plenty to read a receipt.
MAX_SIDE = 4000

MEGABYTE = 1024 * 1024

NOT_ACCEPTED = "Type de fichier non accepté : déposez un PDF ou une photo (JPEG, PNG, HEIC, WebP)."
TOO_LARGE_IMAGE = "L’image est trop grande : 50 millions de pixels au plus."
UNREADABLE = "Le fichier est illisible."


class Upright:
    """Turns a photo upright after its EXIF orientation, which the WebP does not keep.

    pilkit's own Transpose reads the orientation through a private method of
    Pillow; ImageOps.exif_transpose is its public way.
    """

    def process(self, image: Image.Image) -> Image.Image:
        return ImageOps.exif_transpose(image)


class WebpPhoto(ImageSpec):
    """A photo in WebP, compressed as a camera does. Pillow writes no metadata
    into it unless told to: neither EXIF nor XMP is carried over.
    """

    processors: ClassVar[list[object]] = [Upright(), ResizeToFit(MAX_SIDE, MAX_SIDE, upscale=False)]
    format = "WEBP"
    # Method 2 rather than 4: the same size within 1 %, in 40 % less time on a
    # 12-megapixel photo, which the server's single core feels.
    options: ClassVar[dict[str, object]] = {"quality": 85, "method": 2}


class WebpPicture(WebpPhoto):
    """A PNG, such as the screenshot of a document, in WebP without loss: its
    text stays sharp.
    """

    # A low effort: a screenshot stays a few kilobytes, and a photo saved as PNG
    # takes a tenth of the time of the default effort, for the same size.
    options: ClassVar[dict[str, object]] = {"lossless": True, "quality": 25, "method": 1}


@dataclass(frozen=True)
class StoredFile:
    """A deposited file as the server keeps it, with the fingerprint of what was sent."""

    content: ContentFile
    name: str
    mime_type: str
    size: int
    sha256: str


def read_upload(file: File, max_size: int | None = None) -> StoredFile:
    """A deposited file ready to store: a PDF, or an image converted to WebP.

    Every refusal is located on the file: empty, too large, of a type not
    accepted, or unreadable.
    """
    if not file.size:
        raise _refusal("Le fichier est vide.")
    if max_size is not None and file.size > max_size:
        raise _refusal(f"Le fichier dépasse la taille maximale de {max_size // MEGABYTE} Mo.")
    # Read once, into memory: the bytes give the fingerprint, then the stored
    # file. Written from them, the file takes the group of its folder, which
    # nginx reads; a temporary upload moved in place would keep its own.
    data = file.read()
    sha256 = hashlib.sha256(data).hexdigest()
    name = PurePath(file.name).name
    if data.startswith(PDF_SIGNATURE):
        return StoredFile(ContentFile(data), name, PDF, len(data), sha256)
    webp = _webp(data)
    return StoredFile(ContentFile(webp), renamed(name, ".webp"), WEBP, len(webp), sha256)


def renamed(name: str, suffix: str) -> str:
    """A file's name with another extension, within the 255 characters stored."""
    return PurePath(name).stem[: 255 - len(suffix)] + suffix


def _webp(data: bytes) -> bytes:
    try:
        # Opening reads the header alone: the size is known before any pixel
        # is decoded.
        with Image.open(BytesIO(data), formats=IMAGE_FORMATS) as image:
            width, height = image.size
            image_format = image.format
    except Image.DecompressionBombError as error:
        raise _refusal(TOO_LARGE_IMAGE) from error
    except UnidentifiedImageError as error:
        raise _refusal(NOT_ACCEPTED) from error
    except OSError as error:
        # A format recognised whose decoder cannot even start, as a WebP cut short.
        raise _refusal(UNREADABLE) from error
    if width * height > MAX_PIXELS:
        raise _refusal(TOO_LARGE_IMAGE)
    spec = WebpPicture if image_format == "PNG" else WebpPhoto
    try:
        return spec(source=ContentFile(data)).generate().read()
    except OSError as error:
        # A header that reads well over pixels that do not, as a file cut
        # short: only decoding tells, Image.verify checking nothing but a PNG.
        raise _refusal(UNREADABLE) from error


def _refusal(message: str) -> ValidationError:
    return ValidationError({"file": message})
