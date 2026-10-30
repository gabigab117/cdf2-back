"""The fictitious albums of the mockup, around its day: 1 October 2026."""

import datetime as dt

import pytest

from events.services.demo import seed_demo_events
from events.services.periods import events_in_period
from photos.models import Album, Photo
from photos.services.demo import seed_demo_albums
from tests.documents.samples import stored_files
from tests.photos.factories import AlbumFactory

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("mockup_day")]

TODAY = dt.date(2026, 10, 1)


def seed():
    seed_demo_events(TODAY)
    return seed_demo_albums(TODAY)


def albums_by_title():
    return {album.title: album for album in Album.objects.all()}


def test_the_seed_writes_the_albums_of_the_mockup(private_files):
    """
    Given the demo events, on the mockup's day
    When the albums of the demonstration are seeded
    Then five albums are written, each with its cover, of a past event on its day but one,
    a year old
    And the brocante's holds photos hidden and awaiting a check, as in the mockup
    And the egg hunt to come takes its previous edition's cover
    """
    demo = seed()

    assert (len(demo.albums), demo.photos) == (5, 36)
    albums = albums_by_title()
    assert {title: (album.published, album.photos.count()) for title, album in albums.items()} == {
        "Brocante 2026": (True, 12),
        "Fête du 14 juillet": (True, 8),
        "Feu de la Saint-Jean": (False, 6),
        "Chasse aux œufs": (True, 6),
        "Coulisses du bureau": (False, 4),
    }
    brocante = albums["Brocante 2026"]
    assert (brocante.date, brocante.event.title) == (dt.date(2026, 9, 13), "Brocante")
    assert (albums["Coulisses du bureau"].date, albums["Coulisses du bureau"].event) == (
        dt.date(2025, 10, 1),
        None,
    )
    assert all(album.cover.album == album for album in albums.values())
    assert brocante.photos.filter(image_rights_to_review=True).count() == 2
    assert brocante.photos.filter(hidden=True).count() == 1
    egg_hunt = events_in_period("upcoming").get(title="Chasse aux œufs")
    assert egg_hunt.cover == albums["Chasse aux œufs"].cover
    assert egg_hunt.previous_edition == albums["Chasse aux œufs"].event
    assert len(stored_files(private_files, "photos")) == 3 * 36


def test_the_seed_runs_again_and_keeps_an_album_made_by_hand(
    private_files, django_capture_on_commit_callbacks
):
    """
    Given the albums of the demonstration, and an album made by hand
    When they are seeded again
    Then the demonstration is written anew, the same drawings, its former files removed
    And the album made by hand stays
    """
    seed()
    drawings = sorted(Photo.objects.values_list("sha256", flat=True))
    by_hand = AlbumFactory(title="Repas des aînés")

    with django_capture_on_commit_callbacks(execute=True):
        seed()

    assert Album.objects.count() == 6
    assert sorted(Photo.objects.values_list("sha256", flat=True)) == drawings
    assert len(stored_files(private_files, "photos")) == 3 * 36
    assert Album.objects.filter(pk=by_hand.pk).exists()
