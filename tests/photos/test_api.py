import pytest

from photos.models import Album, Photo
from photos.services.images import NOT_A_PHOTO
from photos.services.photos import upload_photo
from tests.accounts.factories import UserFactory, client_of
from tests.documents.samples import pdf, phone_photo, stored_files, upload
from tests.events.factories import EventFactory
from tests.helpers import iso, member_json, messages_by_place, send
from tests.photos.factories import AlbumFactory, PhotoFactory

pytestmark = pytest.mark.django_db

ALBUMS = "/api/board/albums"

# Every operation of the board on the albums and photos, naming any id: a
# refusal comes before the object is looked up.
OPERATIONS = [
    ("post", ALBUMS),
    ("post", f"{ALBUMS}/1/photos"),
    ("get", "/api/board/photos/1/thumbnail"),
    ("delete", "/api/board/photos/1"),
]


def photos_url(album_id):
    return f"{ALBUMS}/{album_id}/photos"


def file_url(photo_id, rendition="display"):
    return f"/api/board/photos/{photo_id}/{rendition}"


def public_url(photo_id, rendition="display"):
    return f"/api/public/photos/{photo_id}/{rendition}"


def add_photo(client, album, content=None, name="IMG_0042.jpg"):
    """Add a photo as the album's page sends it: alone."""
    return client.post(photos_url(album.id), {"file": upload(content or phone_photo(), name)})


# Access


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_an_anonymous_visitor_gets_a_401(client, method, path):
    """
    Given a visitor without an access token
    When they create an album, add, read or delete a photo of the board
    Then the API refuses with a 401
    """
    response = getattr(client, method)(path)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentification requise."}


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_an_account_outside_the_board_gets_a_403(method, path):
    """
    Given an active account outside the board
    When it creates an album, adds, reads or deletes a photo of the board
    Then the API refuses with a 403
    """
    response = getattr(client_of(UserFactory()), method)(path)

    assert response.status_code == 403
    assert response.json() == {"detail": "Accès réservé aux membres du bureau."}


# Albums


def test_a_member_creates_a_private_album_of_an_event(board_client):
    """
    Given an event of the committee
    When a member creates an album of it
    Then the album is recorded, private until it is published (D17)
    """
    event = EventFactory(title="Brocante d’automne")

    payload = {"title": "Brocante 2026", "date": "2026-09-13", "event": event.id}

    response = send(board_client, "post", ALBUMS, payload)

    assert response.status_code == 201
    album = Album.objects.get()
    assert response.json() == {
        "id": album.id,
        "title": "Brocante 2026",
        "date": "2026-09-13",
        "event": {"id": event.id, "title": "Brocante d’automne"},
        "published": False,
        "created_at": iso(album.created_at),
    }


def test_an_album_is_refused_without_a_title_or_with_an_unknown_event(board_client):
    """
    Given a title left empty and an event that does not exist
    When a member creates the album
    Then it is refused, each error under its field
    """
    payload = {"title": "", "date": "2026-09-13", "event": 999_999}

    response = send(board_client, "post", ALBUMS, payload)

    assert messages_by_place(response) == {
        ("body", "title"): "Ce champ ne peut pas être vide.",
        ("body", "event"): "Choisissez un événement existant.",
    }
    assert not Album.objects.exists()


def test_an_album_outlives_its_event():
    """
    Given an album of an event
    When the event is deleted
    Then the album stays, without an event
    """
    album = AlbumFactory(event=EventFactory())

    album.event.delete()

    album.refresh_from_db()
    assert album.event is None


# Adding a photo


def test_a_member_adds_a_photo_to_an_album(board_client, board_member, private_files):
    """
    Given an album of the board
    When a member adds a phone's photo to it
    Then the photo is recorded, visible to no one but the board until published
    And its three sizes are stored under random names
    """
    album = AlbumFactory()

    response = add_photo(board_client, album)

    assert response.status_code == 201
    photo = Photo.objects.get()
    assert response.json() == {
        "id": photo.id,
        "original_name": "IMG_0042.webp",
        "width": 30,
        "height": 40,
        "taken_at": None,
        "hidden": False,
        "image_rights_to_review": False,
        "uploaded_by": member_json(board_member),
        "created_at": iso(photo.created_at),
    }
    assert photo.album == album
    names = {photo.image.name, photo.display.name, photo.thumbnail.name}
    assert len(names) == 3
    assert all(name.startswith("photos/") and name.endswith(".webp") for name in names)
    assert len(stored_files(private_files, "photos")) == 3


def test_the_same_photo_twice_in_an_album_is_refused_on_the_file(board_client, private_files):
    """
    Given a photo already in an album
    When a member adds the same file to it again
    Then it is refused on the file, and nothing more is stored
    And the same file is still welcome in another album
    """
    album = AlbumFactory()
    add_photo(board_client, album)

    response = add_photo(board_client, album)

    assert messages_by_place(response) == {("body", "file"): "Cette photo est déjà dans l’album."}
    assert len(stored_files(private_files, "photos")) == 3
    assert add_photo(board_client, AlbumFactory()).status_code == 201


def test_a_file_that_is_not_a_photo_is_refused_and_leaves_no_file(board_client, private_files):
    """
    Given a PDF sent as a photo
    When a member adds it to an album
    Then it is refused on the file, and nothing is stored
    """
    response = add_photo(board_client, AlbumFactory(), pdf(), "facture.pdf")

    assert messages_by_place(response) == {("body", "file"): NOT_A_PHOTO}
    assert stored_files(private_files, "photos") == []


def test_a_photo_for_an_unknown_album_is_not_found(board_client, private_files):
    """
    Given no album of that id
    When a member adds a photo to it
    Then the API answers 404, and nothing is stored
    """
    response = board_client.post(photos_url(999_999), {"file": upload(phone_photo())})

    assert response.status_code == 404
    assert stored_files(private_files, "photos") == []


def test_a_photo_that_fails_to_record_leaves_no_file(board_member, private_files, monkeypatch):
    """
    Given a photo checked and written, whose record then fails
    When the addition is undone
    Then its three files are removed with it
    """

    def failing_save(*args, **kwargs):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(Photo, "save", failing_save)

    with pytest.raises(RuntimeError):
        upload_photo(AlbumFactory(), upload(phone_photo()), board_member)

    assert stored_files(private_files, "photos") == []


# Reading, for the board


@pytest.mark.parametrize("rendition", ["thumbnail", "display"])
def test_a_member_sees_any_photo_in_either_size(board_client, rendition):
    """
    Given a photo of a private album
    When a member opens its thumbnail or its display
    Then the API sends that size in WebP, inline, under its name, kept in no cache
    """
    photo = PhotoFactory()

    response = board_client.get(file_url(photo.id, rendition))

    assert response.status_code == 200
    assert response.getvalue() == getattr(photo, rendition).read()
    assert response["Content-Type"] == "image/webp"
    assert response["Content-Disposition"] == 'inline; filename="IMG_0042.webp"'
    assert set(response["Cache-Control"].split(", ")) == {"private", "no-store"}


def test_a_photo_is_read_in_its_smaller_sizes_only(board_client):
    """
    Given a photo
    When a member asks for a size the API does not serve, such as its image
    Then the API refuses with a 422
    """
    response = board_client.get(file_url(PhotoFactory().id, "image"))

    assert response.status_code == 422


def test_an_unknown_photo_is_not_found(board_client):
    """
    Given no photo of that id
    When a member asks for it
    Then the API answers 404, in French
    """
    response = board_client.get(file_url(999_999))

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}


# Reading, for the site (D17)


def test_a_visitor_sees_a_visible_photo_named_after_nothing_of_its_own(client):
    """
    Given a photo of a published album, neither hidden nor awaiting a check
    When a visitor of the site opens it
    Then the API sends it, under a name that tells nothing of the original
    And the browser checks it again at each showing
    """
    photo = PhotoFactory(visible=True)

    response = client.get(public_url(photo.id, "thumbnail"))

    assert response.status_code == 200
    assert response.getvalue() == photo.thumbnail.read()
    assert response["Content-Type"] == "image/webp"
    assert response["Content-Disposition"] == f'inline; filename="photo-{photo.id}.webp"'
    assert response["Cache-Control"] == "no-cache"


@pytest.mark.parametrize(
    "state",
    [{"album__published": False}, {"hidden": True}, {"image_rights_to_review": True}],
    ids=["private-album", "hidden", "image-rights-to-review"],
)
def test_a_photo_the_site_may_not_show_is_not_found(client, state):
    """
    Given a photo of a private album, hidden from the site, or awaiting a check
    of its image rights
    When a visitor asks for it
    Then the API answers 404, as for no photo at all
    """
    photo = PhotoFactory(visible=True, **state)

    response = client.get(public_url(photo.id))

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}


def test_a_photo_hidden_leaves_the_site_at_once(client):
    """
    Given a photo a visitor has just seen
    When a member hides it from the site
    Then the next visitor's request is not found
    """
    photo = PhotoFactory(visible=True)
    assert client.get(public_url(photo.id)).status_code == 200

    Photo.objects.filter(pk=photo.pk).update(hidden=True)

    assert client.get(public_url(photo.id)).status_code == 404


def test_on_the_server_nginx_sends_the_photo(client, settings):
    """
    Given the server, where nginx sends the private files
    When a visitor opens a visible photo
    Then the API answers with its place under photos/, which nginx marks as not to be indexed
    """
    settings.PRIVATE_FILES_ACCEL_PREFIX = "/_private/"
    photo = PhotoFactory(visible=True)

    response = client.get(public_url(photo.id))

    assert response.content == b""
    assert response["X-Accel-Redirect"] == f"/_private/{photo.display.name}"
    assert response["X-Accel-Redirect"].startswith("/_private/photos/")


# Deletion


def test_a_member_deletes_a_photo_and_its_three_files(
    board_client, private_files, django_capture_on_commit_callbacks
):
    """
    Given the cover of an album, as when the person on it asks for its removal
    When a member deletes it
    Then the photo is gone, its three files once the deletion is done
    And the album has no cover left
    """
    photo = PhotoFactory()
    album = photo.album
    album.cover = photo
    album.save()

    with django_capture_on_commit_callbacks(execute=True):
        response = board_client.delete(f"/api/board/photos/{photo.id}")
        assert len(stored_files(private_files, "photos")) == 3

    assert response.status_code == 204
    assert not Photo.objects.exists()
    assert stored_files(private_files, "photos") == []
    album.refresh_from_db()
    assert album.cover is None


def test_deleting_an_unknown_photo_is_not_found(board_client):
    """
    Given no photo of that id
    When a member deletes it
    Then the API answers 404
    """
    assert board_client.delete("/api/board/photos/999999").status_code == 404
