import datetime as dt

import pytest

from events.models import Event
from photos.services.covers import NOT_A_CHOICE
from tests.events.factories import EventFactory, event_payload
from tests.helpers import messages_by_place, send
from tests.photos.factories import AlbumFactory, PhotoFactory

pytestmark = pytest.mark.django_db


def cover_url(event_id):
    return f"/api/board/events/{event_id}/cover"


def album_ids(response):
    return [album["id"] for album in response.json()["albums"]]


@pytest.fixture
def editions():
    """An event of this year, and its previous edition, each with an album."""
    previous = EventFactory(title="Brocante 2025")
    event = EventFactory(title="Brocante 2026", previous_edition=previous)
    return {
        "event": event,
        "album": AlbumFactory(event=event, date=dt.date(2026, 9, 13)),
        "previous_album": AlbumFactory(event=previous, date=dt.date(2025, 9, 14), published=True),
    }


# The choice


def test_an_event_is_offered_its_albums_and_its_previous_editions(board_client, editions):
    """
    Given an event with an album, its previous edition with another
    And an album of another event, and one of no event
    When a member opens the event's cover
    Then it has none yet, and the albums offered are the event's and its previous
    edition's, the latest first
    """
    AlbumFactory(event=EventFactory())
    AlbumFactory()

    response = board_client.get(cover_url(editions["event"].id))

    assert response.status_code == 200
    assert response.json()["cover"] is None
    assert response.json()["visible"] is False
    assert album_ids(response) == [editions["album"].id, editions["previous_album"].id]


def test_an_event_without_previous_edition_is_offered_its_albums_alone(board_client):
    """
    Given an event without a previous edition, with an album
    And an album of no event
    When a member opens the event's cover
    Then only the event's album is offered
    """
    event = EventFactory()
    album = AlbumFactory(event=event)
    AlbumFactory()

    response = board_client.get(cover_url(event.id))

    assert album_ids(response) == [album.id]


def test_the_cover_reads_its_albums_at_once(board_client, editions, django_assert_max_num_queries):
    """
    Given an event with a cover, and three albums of photos offered
    When a member opens its cover
    Then it takes a fixed number of queries
    """
    event = editions["event"]
    AlbumFactory(event=event)
    Event.objects.filter(pk=event.pk).update(cover=PhotoFactory(album=editions["previous_album"]))

    # Authentication (2), the event, whether its cover shows, the albums offered.
    with django_assert_max_num_queries(5):
        response = board_client.get(cover_url(event.id))

    assert len(response.json()["albums"]) == 3


def test_the_cover_of_an_unknown_event_is_not_found(board_client):
    """
    Given no event of that id
    When a member opens its cover
    Then the API answers 404
    """
    assert board_client.get(cover_url(999_999)).status_code == 404


# Choosing it


def test_a_member_chooses_a_photo_of_the_previous_edition_shown_on_the_site(board_client, editions):
    """
    Given a photo of the previous edition's published album
    When a member chooses it as the event's cover
    Then the event has it, and the site will show it
    And the date of the event's last change stays
    """
    event = editions["event"]
    photo = PhotoFactory(album=editions["previous_album"])
    updated_at = event.updated_at

    response = send(board_client, "put", cover_url(event.id), {"cover": photo.id})

    assert response.status_code == 200
    assert response.json()["cover"] == photo.id
    assert response.json()["visible"] is True
    assert album_ids(response) == [editions["album"].id, editions["previous_album"].id]
    event.refresh_from_db()
    assert event.cover == photo
    assert event.updated_at == updated_at


def test_a_cover_the_site_may_not_show_is_kept_and_said_so(board_client, editions):
    """
    Given a photo of the event's private album
    When a member chooses it as the cover
    Then the event has it, and the site will not show it while the album is private
    """
    photo = PhotoFactory(album=editions["album"])

    response = send(board_client, "put", cover_url(editions["event"].id), {"cover": photo.id})

    assert response.json()["cover"] == photo.id
    assert response.json()["visible"] is False


def test_a_photo_of_another_event_is_refused_as_cover(board_client, editions):
    """
    Given a photo of another event's album
    When a member chooses it as the cover
    Then it is refused under the cover, and the event keeps none
    """
    event = editions["event"]
    photo = PhotoFactory(album=AlbumFactory(event=EventFactory()))

    response = send(board_client, "put", cover_url(event.id), {"cover": photo.id})

    assert messages_by_place(response) == {("body", "cover"): NOT_A_CHOICE}
    event.refresh_from_db()
    assert event.cover is None


def test_a_member_takes_the_cover_off(board_client, editions):
    """
    Given an event with a cover
    When a member takes it off
    Then the event has none
    """
    event = editions["event"]
    Event.objects.filter(pk=event.pk).update(cover=PhotoFactory(album=editions["album"]))

    response = send(board_client, "put", cover_url(event.id), {"cover": None})

    assert response.json()["cover"] is None
    event.refresh_from_db()
    assert event.cover is None


def test_rewriting_an_event_keeps_its_cover(board_client, editions):
    """
    Given an event with a cover
    When a member rewrites the event, which never names its cover
    Then the event keeps it
    """
    event = editions["event"]
    photo = PhotoFactory(album=editions["album"])
    Event.objects.filter(pk=event.pk).update(cover=photo)

    payload = event_payload(title="Brocante d’automne")

    response = send(board_client, "put", f"/api/board/events/{event.id}", payload)

    assert response.status_code == 200
    event.refresh_from_db()
    assert event.cover == photo
