import datetime as dt

import factory
import pytest
from django.utils import timezone

from photos.models import Album, Photo
from tests.accounts.factories import BoardMemberFactory
from tests.documents.samples import stored_files
from tests.events.factories import EventFactory
from tests.helpers import iso, member_json, messages_by_place, send
from tests.photos.factories import AlbumFactory, PhotoFactory

pytestmark = pytest.mark.django_db

ALBUMS = "/api/board/albums"


def album_url(album_id, part=""):
    return f"{ALBUMS}/{album_id}{part}"


def public_url(photo_id):
    return f"/api/public/photos/{photo_id}/display"


def item_json(album, photos_count=0):
    """An album as the board's list writes it."""
    return {
        "id": album.id,
        "title": album.title,
        "date": album.date.isoformat(),
        "event": album.event and {"id": album.event.id, "title": album.event.title},
        "published": album.published,
        "cover": album.cover_id,
        "photos_count": photos_count,
    }


# The list


def test_the_albums_come_the_latest_first_with_their_cover_and_number_of_photos(board_client):
    """
    Given an album of April, and two of September: the latest has a cover among its two photos
    When a member lists the albums
    Then they come by page, the latest day first, and of a day the last created first
    And each says its cover and how many photos it holds
    """
    april = AlbumFactory(title="Chasse aux œufs", date=dt.date(2026, 4, 5))
    first = AlbumFactory(title="Brocante 2026", event=EventFactory(), published=True)
    second = AlbumFactory(title="Coulisses de la brocante")
    first.cover = PhotoFactory(album=first)
    first.save()
    PhotoFactory(album=first)

    response = board_client.get(ALBUMS)

    assert response.status_code == 200
    assert response.json() == {
        "count": 3,
        "items": [item_json(second), item_json(first, photos_count=2), item_json(april)],
    }


def test_the_albums_of_an_event_are_listed_alone(board_client):
    """
    Given an album of an event, one of another event and one of no event
    When a member lists the albums of the first event
    Then only its album comes
    """
    event = EventFactory()
    album = AlbumFactory(event=event)
    AlbumFactory(event=EventFactory())
    AlbumFactory()

    response = board_client.get(ALBUMS, {"event": event.id})

    assert [item["id"] for item in response.json()["items"]] == [album.id]


def test_listing_the_albums_reads_their_events_and_counts_at_once(
    board_client, django_assert_max_num_queries
):
    """
    Given four albums of four events, each with its cover among its photos
    When a member lists the albums
    Then they take a fixed number of queries
    """
    for album in AlbumFactory.create_batch(4, event=factory.SubFactory(EventFactory)):
        album.cover = PhotoFactory(album=album)
        album.save()
        PhotoFactory(album=album)

    # Authentication (2), count and page of albums with their events and counts.
    with django_assert_max_num_queries(4):
        response = board_client.get(ALBUMS)

    assert len(response.json()["items"]) == 4


# An album and its photos


def test_an_album_comes_with_every_photo_in_the_order_taken(board_client):
    """
    Given an album of four photos, added by two members and by an account deleted since
    And two of them taken on known days, out of the order they were added
    When a member opens the album
    Then its photos come as they were taken, those without a date last, as added
    And it counts two members who added them
    """
    album = AlbumFactory()
    member = BoardMemberFactory()
    undated = PhotoFactory(album=album, uploaded_by=member)
    later = PhotoFactory(album=album, uploaded_by=member, taken_at=timezone.now())
    earlier = PhotoFactory(album=album, taken_at=timezone.now() - dt.timedelta(days=1))
    deleted = PhotoFactory(album=album, uploaded_by=None)

    response = board_client.get(album_url(album.id))

    assert response.status_code == 200
    body = response.json()
    order = [earlier.id, later.id, undated.id, deleted.id]
    assert [photo["id"] for photo in body["photos"]] == order
    assert body["photos_count"] == 4
    assert body["contributors_count"] == 2
    assert body["photos"][2] == {
        "id": undated.id,
        "original_name": "IMG_0042.webp",
        "width": 40,
        "height": 30,
        "taken_at": None,
        "hidden": False,
        "image_rights_to_review": False,
        "uploaded_by": member_json(member),
        "created_at": iso(undated.created_at),
    }


def test_an_album_reads_its_photos_and_their_members_at_once(
    board_client, django_assert_max_num_queries
):
    """
    Given an album of six photos, added by three members
    When a member opens it
    Then it takes a fixed number of queries
    """
    album = AlbumFactory(event=EventFactory())
    for member in BoardMemberFactory.create_batch(3):
        PhotoFactory.create_batch(2, album=album, uploaded_by=member)

    # Authentication (2), the album with its counts, its photos with their members.
    with django_assert_max_num_queries(4):
        response = board_client.get(album_url(album.id))

    assert response.json()["contributors_count"] == 3


def test_an_unknown_album_is_not_found(board_client):
    """
    Given no album of that id
    When a member opens it
    Then the API answers 404, in French
    """
    response = board_client.get(album_url(999_999))

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}


# Correcting an album


def test_a_member_corrects_an_album(board_client):
    """
    Given an album of no event
    When a member gives it another title, another day and an event
    Then the album is rewritten, its photos kept
    """
    album = AlbumFactory()
    PhotoFactory(album=album)
    event = EventFactory(title="Fête du 14 juillet")
    payload = {"title": "Fête du 14 juillet", "date": "2026-07-14", "event": event.id}

    response = send(board_client, "put", album_url(album.id), payload)

    assert response.status_code == 200
    assert response.json()["event"] == {"id": event.id, "title": "Fête du 14 juillet"}
    assert response.json()["photos_count"] == 1
    album.refresh_from_db()
    assert album.title == "Fête du 14 juillet"
    assert (album.date, album.event) == (dt.date(2026, 7, 14), event)


def test_a_correction_is_refused_under_its_fields(board_client):
    """
    Given an album
    When a member empties its title and names an event that does not exist
    Then it is refused, each error under its field, and the album stays as it was
    """
    album = AlbumFactory(title="Brocante 2026")
    payload = {"title": "", "date": "2026-09-13", "event": 999_999}

    response = send(board_client, "put", album_url(album.id), payload)

    assert messages_by_place(response) == {
        ("body", "title"): "Ce champ ne peut pas être vide.",
        ("body", "event"): "Choisissez un événement existant.",
    }
    album.refresh_from_db()
    assert album.title == "Brocante 2026"


# Publishing (D17)


def test_a_published_album_shows_its_photos_until_it_is_taken_off_the_site(board_client, client):
    """
    Given a private album, whose photo the site does not show
    When a member makes it visible on the site
    Then the site shows its photo
    And when the member takes it off, the site no longer shows it, at once
    """
    photo = PhotoFactory()
    album_id = photo.album_id
    assert client.get(public_url(photo.id)).status_code == 404

    response = send(board_client, "put", album_url(album_id, "/published"), {"published": True})

    assert response.status_code == 200
    assert response.json()["published"] is True
    assert client.get(public_url(photo.id)).status_code == 200

    send(board_client, "put", album_url(album_id, "/published"), {"published": False})

    assert client.get(public_url(photo.id)).status_code == 404


# The cover of an album


def test_a_member_chooses_a_photo_of_the_album_as_its_cover_then_none(board_client):
    """
    Given an album of two photos
    When a member chooses the second as its cover, then none
    Then the album says its cover, then has none
    """
    album = AlbumFactory()
    PhotoFactory(album=album)
    photo = PhotoFactory(album=album)

    response = send(board_client, "put", album_url(album.id, "/cover"), {"cover": photo.id})

    assert response.status_code == 200
    assert response.json()["cover"] == photo.id

    response = send(board_client, "put", album_url(album.id, "/cover"), {"cover": None})

    assert response.json()["cover"] is None


def test_a_photo_of_another_album_is_refused_as_cover(board_client):
    """
    Given a photo of another album
    When a member chooses it as an album's cover
    Then it is refused under the cover, and the album keeps none
    """
    album = AlbumFactory()
    payload = {"cover": PhotoFactory().id}

    response = send(board_client, "put", album_url(album.id, "/cover"), payload)

    assert messages_by_place(response) == {("body", "cover"): "Choisissez une photo de l’album."}
    album.refresh_from_db()
    assert album.cover is None


# Deleting an album


def test_a_member_deletes_an_album_its_photos_and_their_files(
    board_client, private_files, django_capture_on_commit_callbacks
):
    """
    Given an album of two photos, one of them an event's cover
    When a member deletes the album
    Then the album and its photos are gone, their six files once the deletion is done
    And the event has no cover left, while another album keeps its photo
    """
    album = AlbumFactory()
    cover = PhotoFactory(album=album)
    PhotoFactory(album=album)
    event = EventFactory(cover=cover)
    other = PhotoFactory()

    with django_capture_on_commit_callbacks(execute=True):
        response = board_client.delete(album_url(album.id))
        assert len(stored_files(private_files, "photos")) == 9

    assert response.status_code == 204
    assert not Album.objects.filter(pk=album.pk).exists()
    assert list(Photo.objects.all()) == [other]
    assert len(stored_files(private_files, "photos")) == 3
    event.refresh_from_db()
    assert event.cover is None
