import datetime as dt
import zipfile
from io import BytesIO

import pytest
from django.utils import timezone

from photos.models import Photo
from tests.documents.samples import stored_files
from tests.events.factories import EventFactory
from tests.helpers import messages_by_place, send
from tests.photos.factories import IMAGE, AlbumFactory, PhotoFactory

pytestmark = pytest.mark.django_db


def selection_url(album, action):
    return f"/api/board/albums/{album.id}/photos/{action}"


def flags(*photos):
    """Whether each photo is hidden, and whether it awaits a check of its image rights."""
    return [
        (photo.hidden, photo.image_rights_to_review)
        for photo in Photo.objects.filter(pk__in=[photo.pk for photo in photos]).order_by("pk")
    ]


# Hiding and image rights


def test_a_member_hides_the_selected_photos_then_shows_them_again(board_client):
    """
    Given an album of three photos
    When a member hides two of them from the site
    Then those two are hidden, and the third is not
    And when the member shows them again, none is hidden
    """
    album = AlbumFactory()
    first, second, third = PhotoFactory.create_batch(3, album=album)
    payload = {"photos": [first.id, third.id], "hidden": True}

    response = send(board_client, "put", selection_url(album, "hidden"), payload)

    assert response.status_code == 204
    assert flags(first, second, third) == [(True, False), (False, False), (True, False)]

    send(board_client, "put", selection_url(album, "hidden"), payload | {"hidden": False})

    assert flags(first, second, third) == [(False, False), (False, False), (False, False)]


def test_a_member_holds_the_selected_photos_for_their_image_rights_then_releases_them(
    board_client,
):
    """
    Given an album of two photos
    When a member marks one as awaiting a check of its image rights
    Then that one alone awaits it
    And when the member releases it, none does
    """
    album = AlbumFactory()
    first, second = PhotoFactory.create_batch(2, album=album)
    payload = {"photos": [second.id], "image_rights_to_review": True}

    response = send(board_client, "put", selection_url(album, "image-rights-to-review"), payload)

    assert response.status_code == 204
    assert flags(first, second) == [(False, False), (False, True)]

    send(
        board_client,
        "put",
        selection_url(album, "image-rights-to-review"),
        payload | {"image_rights_to_review": False},
    )

    assert flags(first, second) == [(False, False), (False, False)]


@pytest.mark.parametrize("foreign", [True, False], ids=["photo-of-another-album", "empty"])
def test_a_selection_is_refused_unless_every_photo_is_of_the_album(board_client, foreign):
    """
    Given a selection holding a photo of another album, or no photo at all
    When a member hides it
    Then it is refused under the photos, and no photo changes
    """
    album = AlbumFactory()
    photo = PhotoFactory(album=album)
    other = PhotoFactory()
    selected = [photo.id, other.id] if foreign else []

    response = send(
        board_client, "put", selection_url(album, "hidden"), {"photos": selected, "hidden": True}
    )

    assert messages_by_place(response) == {("body", "photos"): "Choisissez des photos de l’album."}
    assert flags(photo, other) == [(False, False), (False, False)]


# Deleting a selection (D17: also a removal asked for)


def test_a_member_deletes_the_selected_photos_and_their_files(
    board_client, private_files, django_capture_on_commit_callbacks
):
    """
    Given an album of three photos, the first its cover and an event's
    When a member deletes the first two, as when the person on them asks for it
    Then they are gone, their six files once the deletion is done
    And neither the album nor the event has a cover left, while the third photo stays
    """
    album = AlbumFactory()
    first, second, third = PhotoFactory.create_batch(3, album=album)
    album.cover = first
    album.save()
    event = EventFactory(cover=first)

    with django_capture_on_commit_callbacks(execute=True):
        response = send(
            board_client, "post", selection_url(album, "delete"), {"photos": [first.id, second.id]}
        )
        assert len(stored_files(private_files, "photos")) == 9

    assert response.status_code == 204
    assert list(Photo.objects.all()) == [third]
    assert len(stored_files(private_files, "photos")) == 3
    album.refresh_from_db()
    event.refresh_from_db()
    assert album.cover is None
    assert event.cover is None


def test_a_deletion_refused_leaves_every_photo(board_client, private_files):
    """
    Given a selection holding a photo of another album
    When a member deletes it
    Then it is refused, and every photo and file stays
    """
    album = AlbumFactory()
    photo = PhotoFactory(album=album)

    response = send(
        board_client,
        "post",
        selection_url(album, "delete"),
        {"photos": [photo.id, PhotoFactory().id]},
    )

    assert messages_by_place(response) == {("body", "photos"): "Choisissez des photos de l’album."}
    assert Photo.objects.count() == 2
    assert len(stored_files(private_files, "photos")) == 6


# The zip of a selection


def test_a_member_downloads_the_selected_images_in_a_zip(board_client):
    """
    Given an album of four photos, three of them sent under the same name
    When a member downloads three of them
    Then a zip comes, named after the album, kept in no cache
    And it holds their images in the album's order, a name given already taking « (2) », « (3) »
    """
    album = AlbumFactory(title="Fête du 14 juillet")
    later = PhotoFactory(album=album, taken_at=timezone.now())
    earlier = PhotoFactory(album=album, taken_at=timezone.now() - dt.timedelta(days=1))
    undated = PhotoFactory(album=album)
    PhotoFactory(album=album, original_name="IMG_0043.webp")

    response = send(
        board_client,
        "post",
        selection_url(album, "zip"),
        {"photos": [undated.id, later.id, earlier.id]},
    )

    assert response.status_code == 200
    assert response.streaming
    assert response["Content-Type"] == "application/zip"
    assert response["Content-Disposition"] == (
        "attachment; filename*=utf-8''F%C3%AAte%20du%2014%20juillet.zip"
    )
    assert set(response["Cache-Control"].split(", ")) == {"private", "no-store"}
    archive = zipfile.ZipFile(BytesIO(response.getvalue()))
    assert archive.namelist() == ["IMG_0042.webp", "IMG_0042 (2).webp", "IMG_0042 (3).webp"]
    assert all(archive.read(name) == IMAGE for name in archive.namelist())


def test_the_zip_is_sent_image_by_image(board_client):
    """
    Given two photos of an album
    When a member downloads them
    Then the zip comes image by image, then its directory: the server never holds
    more than one image
    """
    album = AlbumFactory()
    photos = PhotoFactory.create_batch(2, album=album)

    response = send(
        board_client, "post", selection_url(album, "zip"), {"photos": [p.id for p in photos]}
    )

    pieces = list(response.streaming_content)
    assert len(pieces) == 3
    assert [piece.count(IMAGE) for piece in pieces] == [1, 1, 0]
    assert zipfile.ZipFile(BytesIO(b"".join(pieces))).testzip() is None


def test_a_zip_refused_is_refused_before_it_starts(board_client):
    """
    Given a selection holding a photo of another album
    When a member downloads it
    Then the API answers a 422 in JSON, not a zip
    """
    album = AlbumFactory()

    response = send(
        board_client, "post", selection_url(album, "zip"), {"photos": [PhotoFactory().id]}
    )

    assert messages_by_place(response) == {("body", "photos"): "Choisissez des photos de l’album."}
