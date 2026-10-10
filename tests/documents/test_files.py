import hashlib

import pytest
from django.core.exceptions import ValidationError

from documents.services.files import (
    MAX_SIDE,
    NOT_ACCEPTED,
    PDF,
    TOO_LARGE_IMAGE,
    UNREADABLE,
    WEBP,
    read_upload,
    renamed,
)
from tests.documents.samples import (
    GPS,
    MAKE,
    ORIENTATION,
    image,
    noise,
    opened,
    pdf,
    phone_photo,
    upload,
)


def refusal(file, **options):
    """The message a refused file gets, located on the file."""
    with pytest.raises(ValidationError) as caught:
        read_upload(file, **options)
    return caught.value.message_dict


# PDF


def test_a_pdf_is_kept_as_it_was_sent():
    """
    Given a PDF deposited by a member
    When the server reads it
    Then it keeps the file as it is, under its name, as a PDF
    And the fingerprint is that of the bytes sent
    """
    content = pdf("Facture — Location sono")

    stored = read_upload(upload(content, "facture-sono.pdf"))

    assert stored.content.read() == content
    assert (stored.name, stored.mime_type, stored.size) == ("facture-sono.pdf", PDF, len(content))
    assert stored.sha256 == hashlib.sha256(content).hexdigest()


# Images


def test_a_phone_photo_becomes_an_upright_webp_without_its_metadata():
    """
    Given a JPEG taken by a phone held upright, which records where it was taken
    When the server reads it
    Then it stores a WebP, turned upright
    And neither the place, the phone nor the comment is kept
    And the fingerprint is still that of the JPEG sent
    """
    content = phone_photo(size=(40, 30), orientation=6)

    stored = read_upload(upload(content, "IMG_0042.jpg"))

    webp = opened(stored.content.read())
    assert (stored.name, stored.mime_type, webp.format) == ("IMG_0042.webp", WEBP, "WEBP")
    assert webp.size == (30, 40)
    assert not {MAKE, ORIENTATION, GPS} & set(webp.getexif())
    assert not {"exif", "xmp", "comment"} & set(webp.info)
    assert stored.sha256 == hashlib.sha256(content).hexdigest()


def test_an_iphone_heic_photo_becomes_a_webp():
    """
    Given a photo of an iPhone, in HEIC
    When the server reads it
    Then it stores a WebP that every browser shows
    """
    stored = read_upload(upload(image("HEIF", size=(30, 20)), "IMG_0042.HEIC"))

    webp = opened(stored.content.read())
    assert (stored.name, webp.format, webp.size) == ("IMG_0042.webp", "WEBP", (30, 20))


@pytest.mark.parametrize("mode", ["RGB", "L", "P", "I;16", "1"])
def test_a_png_becomes_a_webp_without_loss(mode):
    """
    Given a PNG, such as a screenshot or a scan in shades of grey
    When the server reads it
    Then it stores a WebP whose pixels are those of the PNG
    """
    content = image("PNG", mode=mode)

    stored = read_upload(upload(content, "capture.png"))

    webp = opened(stored.content.read())
    assert webp.format == "WEBP"
    assert webp.convert("RGB").tobytes() == opened(content).convert("RGB").tobytes()


def test_a_transparent_png_keeps_its_transparency():
    """
    Given a PNG with a transparent background
    When the server reads it
    Then the WebP keeps the transparency
    """
    stored = read_upload(upload(image("PNG", mode="RGBA", color=(0, 0, 0, 0)), "logo.png"))

    assert opened(stored.content.read()).mode == "RGBA"


def test_a_webp_and_a_cmyk_jpeg_are_accepted():
    """
    Given a WebP picture, and a scan saved as a CMYK JPEG
    When the server reads them
    Then both are stored as WebP
    """
    for content in (image("WEBP"), image("JPEG", mode="CMYK")):
        assert opened(read_upload(upload(content, "scan")).content.read()).format == "WEBP"


def test_a_large_image_is_reduced_to_its_longest_side():
    """
    Given a photo wider than what is kept
    When the server reads it
    Then the WebP is reduced to that width, in proportion
    And a photo within the limit keeps its size
    """
    reduced = read_upload(upload(image("JPEG", size=(MAX_SIDE + 1000, 1000)), "large.jpg"))
    kept = read_upload(upload(image("JPEG", size=(MAX_SIDE, 3000)), "kept.jpg"))

    assert opened(reduced.content.read()).size == (MAX_SIDE, 800)
    assert opened(kept.content.read()).size == (MAX_SIDE, 3000)


def test_a_long_name_keeps_within_what_is_stored():
    """
    Given a file whose name already fills the 255 characters stored
    When its extension becomes .webp
    Then its name is shortened, and keeps the new extension
    """
    name = renamed("a" * 251 + ".jpg", ".webp")

    assert len(name) == 255
    assert name.endswith("a.webp")


# Refusals


def test_an_empty_file_is_refused():
    """
    Given a file with nothing in it
    When the server reads it
    Then it is refused on the file
    """
    assert refusal(upload(b"", "vide.pdf")) == {"file": ["Le fichier est vide."]}


def test_a_file_over_the_maximum_size_is_refused():
    """
    Given a maximum size of 1 MB, and a larger file
    When the server reads it
    Then it is refused, the maximum size told
    """
    file = upload(pdf("x" * 1024 * 1024))

    assert refusal(file, max_size=1024 * 1024) == {
        "file": ["Le fichier dépasse la taille maximale de 1 Mo."]
    }


@pytest.mark.parametrize(
    ("content", "name"),
    [
        (b"Ceci est une note.", "note.txt"),
        (b"<html><script>alert('piege')</script></html>", "facture.pdf"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>', "photo.png"),
        (image("GIF"), "anime.gif"),
    ],
    ids=["text", "html-named-pdf", "svg-named-png", "gif"],
)
def test_a_file_of_another_type_is_refused_whatever_its_name(content, name):
    """
    Given a file that is neither a PDF nor an accepted image, whatever its name says
    When the server reads it
    Then it is refused, the accepted types told
    """
    assert refusal(upload(content, name)) == {"file": [NOT_ACCEPTED]}


@pytest.mark.parametrize("size", [(8000, 8000), (14000, 14000)], ids=["above-limit", "bomb"])
def test_an_image_of_too_many_pixels_is_refused_before_it_is_decoded(size):
    """
    Given an image of more pixels than the server may hold, a small file for all that
    When the server reads it
    Then it is refused from its header, without decoding its pixels
    """
    content = image("PNG", size=size, mode="1")

    assert refusal(upload(content, "immense.png")) == {"file": [TOO_LARGE_IMAGE]}


@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_an_image_cut_short_is_refused_as_unreadable(image_format):
    """
    Given an image whose file was cut in half on its way
    When the server reads it
    Then it is refused as unreadable, not as a server error
    """
    content = noise(image_format)

    assert refusal(upload(content[: len(content) // 2], "coupee")) == {"file": [UNREADABLE]}
