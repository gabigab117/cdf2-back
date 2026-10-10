"""Fictitious files, made in the tests: no real document belongs to the repository."""

from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

# The smallest file the server takes for a PDF: its header, then its end.
PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog >> endobj\n%%EOF\n"

# The EXIF tags a phone writes: its maker, the orientation it was held in, and
# where the photo was taken.
MAKE = 0x010F
ORIENTATION = 0x0112
GPS = 0x8825
POSITION = {1: "N", 2: (48.0, 51.0, 24.0), 3: "E", 4: (2.0, 21.0, 3.0)}


def pdf(text="Facture fictive"):
    """A PDF whose content, and thus fingerprint, follows its text."""
    return PDF + f"% {text}\n".encode()


def image(image_format, size=(40, 30), mode="RGB", color=(200, 30, 30), **options):
    """An image of one colour, in a format Pillow writes."""
    buffer = BytesIO()
    Image.new(mode, size, color if mode in ("RGB", "RGBA") else 0).save(
        buffer, image_format, **options
    )
    return buffer.getvalue()


def phone_photo(size=(40, 30), orientation=6):
    """A JPEG as a phone takes it: held upright, so stored turned, and located."""
    exif = Image.Exif()
    exif[MAKE] = "Téléphone fictif"
    exif[ORIENTATION] = orientation
    exif[GPS] = POSITION
    return image("JPEG", size, exif=exif, comment=b"Prise au bureau")


def noise(image_format, size=(300, 300)):
    """An image of random pixels, which compresses badly: cut in half, it is broken."""
    buffer = BytesIO()
    Image.effect_noise(size, 64).convert("RGB").save(buffer, image_format)
    return buffer.getvalue()


def upload(content, name="facture.pdf"):
    """A file as a browser sends it."""
    return SimpleUploadedFile(name, content)


def opened(content):
    """The image a stored file holds."""
    return Image.open(BytesIO(content))
