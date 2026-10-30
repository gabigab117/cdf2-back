from tests.photos.factories import AlbumFactory, PhotoFactory


def test_an_album_reads_as_its_title_and_a_photo_as_its_name():
    """
    Given an album and one of its photos
    When they are named, as the Django admin would
    Then the album reads as its title, the photo as the name it was sent under
    """
    assert str(AlbumFactory.build(title="Brocante 2026")) == "Brocante 2026"
    assert str(PhotoFactory.build(original_name="IMG_0042.webp")) == "IMG_0042.webp"
