import datetime as dt
import hashlib

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from PIL import ExifTags, Image

from documents.services.files import MAX_SIDE, TOO_LARGE_IMAGE, UNREADABLE
from photos.services.images import DISPLAY_SIDE, NOT_A_PHOTO, THUMBNAIL_SIDE, read_photo
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


def sizes(stored):
    """The three sizes of a stored photo, opened: image, display, thumbnail."""
    return [opened(file.read()) for file in (stored.image, stored.display, stored.thumbnail)]


def taken(moment):
    """A JPEG whose camera recorded when it took it, as it writes it."""
    exif = Image.Exif()
    exif.get_ifd(ExifTags.IFD.Exif)[ExifTags.Base.DateTimeOriginal] = moment
    return image("JPEG", exif=exif)


def refusal(file):
    """The message a refused photo gets, located on the file."""
    with pytest.raises(ValidationError) as caught:
        read_photo(file)
    return caught.value.message_dict


def test_a_phone_photo_becomes_three_upright_webp_without_its_metadata():
    """
    Given a JPEG taken by a phone held upright, which records where it was taken
    When the server reads it
    Then it keeps three WebP, each turned upright
    And none keeps the place, the phone or the comment
    And the photo is named and measured after its image, its fingerprint that of the JPEG
    """
    content = phone_photo(size=(40, 30), orientation=6)

    stored = read_photo(upload(content, "IMG_0042.jpg"))

    for webp in sizes(stored):
        assert (webp.format, webp.size) == ("WEBP", (30, 40))
        assert not {MAKE, ORIENTATION, GPS} & set(webp.getexif())
        assert not {"exif", "xmp", "comment"} & set(webp.info)
    assert (stored.name, stored.width, stored.height) == ("IMG_0042.webp", 30, 40)
    assert stored.sha256 == hashlib.sha256(content).hexdigest()


def test_each_size_is_reduced_to_its_longest_side_in_proportion():
    """
    Given a photo wider than its image keeps
    When the server reads it
    Then the image, the display and the thumbnail each fit their longest side
    """
    stored = read_photo(upload(image("JPEG", size=(MAX_SIDE + 1000, 2500)), "large.jpg"))

    assert [webp.size for webp in sizes(stored)] == [
        (MAX_SIDE, 2000),
        (DISPLAY_SIDE, 1024),
        (THUMBNAIL_SIDE, 320),
    ]
    assert (stored.width, stored.height) == (MAX_SIDE, 2000)


def test_a_small_photo_is_never_enlarged():
    """
    Given a photo smaller than a thumbnail
    When the server reads it
    Then its three sizes keep its own
    """
    stored = read_photo(upload(image("JPEG", size=(60, 40)), "petite.jpg"))

    assert [webp.size for webp in sizes(stored)] == [(60, 40)] * 3


def test_an_iphone_heic_photo_and_a_png_are_accepted():
    """
    Given a photo of an iPhone in HEIC, and a picture in PNG
    When the server reads them
    Then both are kept in WebP, and the PNG's image keeps its pixels
    """
    heic = read_photo(upload(image("HEIF", size=(30, 20)), "IMG_0042.HEIC"))
    png = image("PNG", mode="P")
    picture = read_photo(upload(png, "affiche.png"))

    assert [webp.format for webp in sizes(heic)] == ["WEBP"] * 3
    kept = opened(picture.image.read()).convert("RGB")
    assert kept.tobytes() == opened(png).convert("RGB").tobytes()


def test_the_time_a_camera_recorded_is_read_in_paris_time():
    """
    Given a photo whose camera recorded when it was taken, without a zone
    When the server reads it
    Then the photo is dated by it, in Paris time, before its metadata is dropped
    """
    stored = read_photo(upload(taken("2025:10:31 19:42:05"), "halloween.jpg"))

    assert stored.taken_at == timezone.make_aware(dt.datetime(2025, 10, 31, 19, 42, 5))
    assert stored.taken_at.utcoffset() == dt.timedelta(hours=1)


@pytest.mark.parametrize(
    "content",
    [image("JPEG"), taken("0000:00:00 00:00:00"), phone_photo()],
    ids=["no-exif", "blank-date", "no-date"],
)
def test_a_photo_without_a_readable_time_is_not_dated(content):
    """
    Given a photo whose camera recorded no time, or a blank one
    When the server reads it
    Then the photo has no date of its own
    """
    assert read_photo(upload(content, "photo.jpg")).taken_at is None


@pytest.mark.parametrize(
    ("content", "name"),
    [
        (pdf(), "facture.pdf"),
        (b"<html><script>alert('piege')</script></html>", "photo.jpg"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"><script/></svg>', "photo.png"),
    ],
    ids=["pdf", "html-named-jpg", "svg-named-png"],
)
def test_anything_but_an_image_is_refused_whatever_its_name(content, name):
    """
    Given a PDF, or a page disguised as a photo by its name
    When the server reads it as a photo
    Then it is refused, the accepted types told
    """
    assert refusal(upload(content, name)) == {"file": [NOT_A_PHOTO]}


def test_a_photo_over_its_maximum_size_is_refused(settings):
    """
    Given a maximum size of 1 MB for a photo, and a larger one
    When the server reads it
    Then it is refused, the maximum size told
    """
    settings.PHOTO_MAX_SIZE = 1024 * 1024

    assert refusal(upload(noise("PNG", size=(800, 800)), "lourde.png")) == {
        "file": ["Le fichier dépasse la taille maximale de 1 Mo."]
    }


def test_a_photo_too_large_or_cut_short_is_refused():
    """
    Given an image of too many pixels, and a photo cut in half on its way
    When the server reads them
    Then each is refused, on the file
    """
    content = noise("JPEG")

    assert refusal(upload(image("PNG", size=(8000, 8000), mode="1"))) == {"file": [TOO_LARGE_IMAGE]}
    assert refusal(upload(content[: len(content) // 2], "coupee.jpg")) == {"file": [UNREADABLE]}
