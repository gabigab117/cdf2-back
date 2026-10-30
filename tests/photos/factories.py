import datetime as dt

import factory

from photos.models import Album, Photo
from tests.accounts.factories import BoardMemberFactory
from tests.documents.samples import image

# A photo's three sizes, each a WebP of its own: a test tells which one it got.
IMAGE = image("WEBP", size=(40, 30))
DISPLAY = image("WEBP", size=(20, 15))
THUMBNAIL = image("WEBP", size=(8, 6))


class AlbumFactory(factory.django.DjangoModelFactory):
    """An album of the board, private, as every album is when created (D17)."""

    class Meta:
        model = Album

    title = factory.Sequence(lambda n: f"Brocante 2026 ({n})")
    date = dt.date(2026, 9, 13)


class PhotoFactory(factory.django.DjangoModelFactory):
    """A photo added by a board member, to a private album: three WebP, one per size.

    Its fingerprint is a distinct number of its own: a test of duplicates sends
    a real file twice.
    """

    class Meta:
        model = Photo

    album = factory.SubFactory(AlbumFactory)
    image = factory.django.FileField(filename="photo.webp", data=IMAGE)
    display = factory.django.FileField(filename="photo.webp", data=DISPLAY)
    thumbnail = factory.django.FileField(filename="photo.webp", data=THUMBNAIL)
    original_name = "IMG_0042.webp"
    sha256 = factory.Sequence(lambda n: f"{n:064x}")
    width = 40
    height = 30
    uploaded_by = factory.SubFactory(BoardMemberFactory)

    class Params:
        # Of a published album, neither hidden nor awaiting a check: shown on
        # the site (D17). `PhotoFactory(visible=True)`.
        visible = factory.Trait(album=factory.SubFactory(AlbumFactory, published=True))
