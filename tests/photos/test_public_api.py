import datetime as dt

import pytest

from tests.events.factories import EventFactory
from tests.photos.factories import AlbumFactory, PhotoFactory

pytestmark = pytest.mark.django_db

ALBUMS = "/api/public/albums"
EVENTS = "/api/public/events"

# A photo the site may not show (D17), album aside.
NOT_SHOWN = [{"hidden": True}, {"image_rights_to_review": True}]


def taken(hour):
    return dt.datetime(2026, 4, 5, hour, tzinfo=dt.UTC)


def published_album(**fields):
    return AlbumFactory(published=True, **fields)


# The albums of the site


def test_the_site_lists_the_albums_with_a_visible_photo_the_latest_first(client):
    """
    Given two published albums with a visible photo, of September and July
    And a private album, a published one whose photos the site may not show,
    and an empty published one
    When a visitor lists the albums
    Then only the first two come, September's first
    """
    PhotoFactory(album=published_album(title="Fête du 14 juillet", date=dt.date(2026, 7, 14)))
    PhotoFactory(album=published_album(title="Brocante", date=dt.date(2026, 9, 13)))
    PhotoFactory(album=AlbumFactory(title="Coulisses du bureau"))
    hidden_away = published_album(title="Feu de la Saint-Jean")
    for state in NOT_SHOWN:
        PhotoFactory(album=hidden_away, **state)
    published_album(title="Repas des aînés")

    titles = [album["title"] for album in client.get(ALBUMS).json()["items"]]
    assert titles == ["Brocante", "Fête du 14 juillet"]


def test_a_site_album_holds_its_address_its_cover_and_its_visible_photos_only(client):
    """
    Given a published album with a ligature and an apostrophe in its title
    And a visible photo as its cover, a hidden photo and one awaiting a check
    When a visitor lists the albums
    Then it comes with an address made of its number and its title
    And counts its visible photo alone, with no one's name
    """
    album = published_album(title="Chasse aux œufs d’avril", date=dt.date(2026, 4, 5))
    album.cover = PhotoFactory(album=album)
    album.save()
    for state in NOT_SHOWN:
        PhotoFactory(album=album, **state)

    assert client.get(ALBUMS).json()["items"] == [
        {
            "slug": f"{album.id}-chasse-aux-oeufs-d-avril",
            "title": "Chasse aux œufs d’avril",
            "date": "2026-04-05",
            "cover": album.cover.id,
            "photos_count": 1,
        }
    ]


@pytest.mark.parametrize("cover", [None, *NOT_SHOWN], ids=["none", "hidden", "to-review"])
def test_an_album_without_a_cover_the_site_may_show_is_shown_by_its_first_photo(client, cover):
    """
    Given a published album with no cover, or one the site may not show
    And three visible photos: taken at noon, taken at ten, and of no date
    When a visitor lists the albums
    Then the album shows the photo taken first
    """
    album = published_album()
    PhotoFactory(album=album, taken_at=None)
    PhotoFactory(album=album, taken_at=taken(12))
    first = PhotoFactory(album=album, taken_at=taken(10))
    if cover is not None:
        album.cover = PhotoFactory(album=album, taken_at=taken(8), **cover)
        album.save()

    assert client.get(ALBUMS).json()["items"][0]["cover"] == first.id


def test_the_site_s_albums_come_by_page(client):
    """
    Given three albums of the site
    When a visitor asks for pages of two
    Then the second page holds the oldest, and the count is three
    """
    for month in (3, 6, 9):
        PhotoFactory(album=published_album(title=f"Album {month}", date=dt.date(2026, month, 1)))

    response = client.get(ALBUMS, {"page": 2, "page_size": 2})

    assert response.json()["count"] == 3
    assert [album["title"] for album in response.json()["items"]] == ["Album 3"]


def test_listing_the_site_s_albums_counts_and_covers_at_once(client, django_assert_max_num_queries):
    """
    Given four albums of the site, each with photos and a cover
    When a visitor lists the albums
    Then they take a fixed number of queries
    """
    for album in AlbumFactory.create_batch(4, published=True):
        album.cover = PhotoFactory(album=album)
        album.save()
        PhotoFactory(album=album)

    # Count and page, covers and counts within.
    with django_assert_max_num_queries(2):
        response = client.get(ALBUMS)

    assert len(response.json()["items"]) == 4


# An album's page


def test_an_album_page_holds_its_visible_photos_in_the_order_they_were_taken(client):
    """
    Given a published album: a photo of no date, one taken at noon, one at ten,
    one hidden and one awaiting a check
    When a visitor opens the album
    Then its three visible photos come as they were taken, the one of no date last
    """
    album = published_album(title="Brocante", date=dt.date(2026, 9, 13))
    undated = PhotoFactory(album=album, taken_at=None)
    noon = PhotoFactory(album=album, taken_at=taken(12))
    ten = PhotoFactory(album=album, taken_at=taken(10))
    for state in NOT_SHOWN:
        PhotoFactory(album=album, taken_at=taken(9), **state)

    response = client.get(f"{ALBUMS}/{album.id}")

    assert response.status_code == 200
    assert response.json() == {
        "slug": f"{album.id}-brocante",
        "title": "Brocante",
        "date": "2026-09-13",
        "cover": ten.id,
        "photos_count": 3,
        "photos": [ten.id, noon.id, undated.id],
    }


@pytest.mark.parametrize("hidden", [False, True], ids=["private", "nothing-visible"])
def test_an_album_the_site_does_not_show_is_not_found(client, hidden):
    """
    Given a private album with a photo, or a published one whose photo is hidden
    When a visitor opens it
    Then the API answers 404, as for no album at all
    """
    photo = PhotoFactory(album__published=hidden, hidden=hidden)

    response = client.get(f"{ALBUMS}/{photo.album_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}


def test_an_unknown_album_is_not_found(client):
    """
    Given no album
    When a visitor opens an album's address
    Then the API answers 404
    """
    assert client.get(f"{ALBUMS}/999999").status_code == 404


def test_an_album_page_reads_its_photos_at_once(client, django_assert_max_num_queries):
    """
    Given an album of the site with six photos
    When a visitor opens it
    Then it takes a fixed number of queries
    """
    album = published_album()
    PhotoFactory.create_batch(6, album=album)

    # The album, its cover and count within, then its photos.
    with django_assert_max_num_queries(2):
        response = client.get(f"{ALBUMS}/{album.id}")

    assert len(response.json()["photos"]) == 6


# On an event's page


@pytest.mark.parametrize(
    ("state", "shown"),
    [
        ({}, True),
        ({"album__published": False}, False),
        ({"hidden": True}, False),
        ({"image_rights_to_review": True}, False),
    ],
    ids=["visible", "private-album", "hidden", "to-review"],
)
def test_an_event_shows_its_cover_while_the_site_may_show_its_photo(client, state, shown):
    """
    Given a published event to come, whose cover is a photo of a published
    album, of a private one, hidden, or awaiting a check
    When a visitor reads the agenda and the event's page
    Then both give the cover only while the site may show its photo
    """
    event = EventFactory(published=True)
    event.cover = PhotoFactory(visible=True, **state)
    event.save()
    expected = event.cover.id if shown else None

    assert client.get(EVENTS).json()["items"][0]["cover"] == expected
    assert client.get(f"{EVENTS}/{event.slug}").json()["cover"] == expected


@pytest.fixture
def editions():
    """A published event to come, and its previous edition."""
    previous = EventFactory(title="Chasse aux œufs 2025", published=True)
    return {
        "previous": previous,
        "event": EventFactory(
            title="Chasse aux œufs 2026", published=True, previous_edition=previous
        ),
    }


def test_an_event_page_shows_its_previous_edition_s_latest_album(client, editions):
    """
    Given an event whose previous edition has two published albums, of April
    and of March, and a private one of May
    And April's album holds eight visible photos
    When a visitor reads the event's page
    Then « L'an dernier » is April's album, with its first six photos
    """
    previous = editions["previous"]
    april = published_album(title="Chasse aux œufs", event=previous, date=dt.date(2025, 4, 20))
    photos = [PhotoFactory(album=april, taken_at=taken(hour)) for hour in range(8, 16)]
    PhotoFactory(album=published_album(event=previous, date=dt.date(2025, 3, 2)))
    PhotoFactory(album=AlbumFactory(event=previous, date=dt.date(2025, 5, 1)))

    response = client.get(f"{EVENTS}/{editions['event'].slug}")

    assert response.json()["previous_edition_album"] == {
        "slug": f"{april.id}-chasse-aux-oeufs",
        "title": "Chasse aux œufs",
        "date": "2025-04-20",
        "cover": photos[0].id,
        "photos_count": 8,
        "photos": [photo.id for photo in photos[:6]],
    }


def test_an_event_page_has_no_album_of_last_year_the_site_does_not_show(client, editions):
    """
    Given an event whose previous edition has only a private album
    When a visitor reads the event's page
    Then « L'an dernier » is empty
    """
    PhotoFactory(album=AlbumFactory(event=editions["previous"]))

    response = client.get(f"{EVENTS}/{editions['event'].slug}")

    assert response.json()["previous_edition_album"] is None


def test_an_event_page_has_no_album_of_last_year_without_a_previous_edition(client):
    """
    Given a published event without a previous edition, with an album of its own
    When a visitor reads its page
    Then « L'an dernier » is empty: the event's own album is not last year's
    """
    event = EventFactory(published=True)
    PhotoFactory(album=published_album(event=event))

    response = client.get(f"{EVENTS}/{event.slug}")

    assert response.json()["previous_edition_album"] is None


def test_an_event_page_reads_last_year_s_album_at_once(
    client, editions, django_assert_max_num_queries
):
    """
    Given an event whose previous edition has an album of six photos
    When a visitor reads the event's page
    Then it takes a fixed number of queries
    """
    PhotoFactory.create_batch(6, album=published_album(event=editions["previous"]))

    # The event, its programme and practical info, last year's album and its
    # photos, the next events.
    with django_assert_max_num_queries(6):
        response = client.get(f"{EVENTS}/{editions['event'].slug}")

    assert len(response.json()["previous_edition_album"]["photos"]) == 6
