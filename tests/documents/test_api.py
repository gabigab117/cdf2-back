from pathlib import Path

import pytest
from django.core.serializers.json import DjangoJSONEncoder
from django.test import Client
from django.utils import timezone
from ninja_jwt.tokens import AccessToken

from documents.models import Document, DocumentCategory
from documents.schemas import DocumentUploadIn
from documents.services.documents import upload_document
from documents.services.files import NOT_ACCEPTED
from tests.accounts.factories import BoardMemberFactory, UserFactory
from tests.documents.factories import DocumentFactory
from tests.documents.samples import PDF, opened, pdf, phone_photo, upload
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db

DOCUMENTS = "/api/board/documents"

# Every operation on the documents, the paths of a single document naming any
# id: a refusal comes before the document is looked up.
OPERATIONS = [
    ("post", DOCUMENTS),
    ("get", f"{DOCUMENTS}/1/file"),
]


def file_url(document_id):
    return f"{DOCUMENTS}/{document_id}/file"


def iso(moment):
    """A time as the API writes it: to the millisecond, as Django's JSON does."""
    return DjangoJSONEncoder().default(moment)


def member_json(member):
    return {
        "id": member.id,
        "first_name": member.first_name,
        "last_name": member.last_name,
        "email": member.email,
    }


def client_of(member):
    return Client(headers={"Authorization": f"Bearer {AccessToken.for_user(member)}"})


def deposit(client, content=PDF, name="facture-sono.pdf", **fields):
    """Deposit a file as the upload form sends it: the fields left empty are left out."""
    return client.post(DOCUMENTS, {"file": upload(content, name), "category": "invoice"} | fields)


def stored_files(private_files):
    """The files on disk, outside any test of their content."""
    folder = Path(private_files) / "documents"
    return sorted(folder.iterdir()) if folder.exists() else []


def body(response):
    """The bytes of a file, streamed or not."""
    return b"".join(response.streaming_content)


# Access


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_an_anonymous_visitor_gets_a_401(client, method, path):
    """
    Given a visitor without an access token
    When they deposit or read a document
    Then the API refuses with a 401
    """
    response = getattr(client, method)(path)

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentification requise."}


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_an_account_outside_the_board_gets_a_403(method, path):
    """
    Given an active account outside the board
    When it deposits or reads a document
    Then the API refuses with a 403
    """
    response = getattr(client_of(UserFactory()), method)(path)

    assert response.status_code == 403
    assert response.json() == {"detail": "Accès réservé aux membres du bureau."}


# Deposit


def test_a_member_deposits_a_document_to_review(board_client, board_member, private_files):
    """
    Given a board member and an event to come
    When they deposit a PDF, classified as an invoice of that event
    Then the document awaits review, dated by the day of its deposit
    And the file is stored under a random name, as it was sent
    """
    event = EventFactory()

    response = deposit(board_client, pdf(), title="Facture — Location sono", event=event.id)

    assert response.status_code == 201
    document = Document.objects.get()
    assert response.json() == {
        "id": document.id,
        "title": "Facture — Location sono",
        "category": "invoice",
        "status": "to_review",
        "source": "upload",
        "original_name": "facture-sono.pdf",
        "mime_type": "application/pdf",
        "size": len(pdf()),
        "document_date": None,
        "date": timezone.localdate().isoformat(),
        "issuer": "",
        "reference": "",
        "amount": None,
        "due_date": None,
        "paid_on": None,
        "event": {"id": event.id, "title": event.title},
        "note": "",
        "uploaded_by": member_json(board_member),
        "validated_by": None,
        "validated_at": None,
        "created_at": iso(document.created_at),
    }
    [stored] = stored_files(private_files)
    assert stored.name != "facture-sono.pdf"
    assert stored.read_bytes() == pdf()


def test_a_document_is_titled_after_its_file_when_no_title_is_given(board_client):
    """
    Given a file deposited without a title nor an event
    When the document is recorded
    Then its title is the name of the file, without its extension
    """
    response = deposit(board_client, name="devis-animation-60.pdf")

    assert response.json()["title"] == "devis-animation-60"
    assert response.json()["event"] is None


def test_a_photo_is_stored_as_a_webp(board_client, private_files):
    """
    Given a photo of a receipt, taken by a phone
    When it is deposited
    Then the document is a WebP, named after the photo
    """
    response = deposit(board_client, phone_photo(), name="ticket.jpg")

    assert response.json()["original_name"] == "ticket.webp"
    assert response.json()["mime_type"] == "image/webp"
    [stored] = stored_files(private_files)
    assert stored.suffix == ".webp"
    assert opened(stored.read_bytes()).format == "WEBP"


def test_the_same_file_deposited_twice_is_refused_on_the_file(board_client, private_files):
    """
    Given a file already deposited
    When it is deposited again, under another name
    Then the second deposit is refused on the file
    And no second file is left on disk
    """
    deposit(board_client, pdf("Facture"), name="facture.pdf")

    response = deposit(board_client, pdf("Facture"), name="facture (1).pdf")

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "validation_error",
                "loc": ["body", "file"],
                "msg": "Ce fichier a déjà été déposé.",
            }
        ]
    }
    assert Document.objects.count() == 1
    assert len(stored_files(private_files)) == 1


def test_a_file_of_another_type_is_refused(board_client, private_files):
    """
    Given a web page named as a PDF
    When it is deposited
    Then it is refused on the file, and nothing is stored
    """
    response = deposit(board_client, b"<html><body>Facture</body></html>", name="facture.pdf")

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"type": "validation_error", "loc": ["body", "file"], "msg": NOT_ACCEPTED}
    ]
    assert stored_files(private_files) == []


def test_a_file_over_the_maximum_size_is_refused(board_client, settings):
    """
    Given a maximum size of 1 MB
    When a larger file is deposited
    Then it is refused on the file, the maximum size told
    """
    settings.DOCUMENT_MAX_SIZE = 1024 * 1024

    response = deposit(board_client, pdf("x" * 1024 * 1024))

    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "file"],
            "msg": "Le fichier dépasse la taille maximale de 1 Mo.",
        }
    ]


def test_a_deposit_lacking_its_file_or_category_is_refused(board_client):
    """
    Given a deposit sent without a file, nor a category
    When the API reads it
    Then both are refused, each where the form sent it
    """
    response = board_client.post(DOCUMENTS, {"title": "Facture"})

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {"type": "missing", "loc": ["file", "file"], "msg": "Ce champ est obligatoire."},
            {"type": "missing", "loc": ["form", "category"], "msg": "Ce champ est obligatoire."},
        ]
    }


def test_an_unknown_category_or_event_is_refused(board_client):
    """
    Given a deposit naming a category that does not exist, then an event that does not
    When the API reads them
    Then each is refused on its field, in French
    """
    category = deposit(board_client, category="budget")
    event = deposit(board_client, event=999_999)

    assert category.json()["detail"] == [
        {
            "type": "enum",
            "loc": ["form", "category"],
            "msg": "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
        }
    ]
    assert event.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "event"],
            "msg": "Choisissez un événement existant.",
        }
    ]


def test_a_title_too_long_is_refused_and_leaves_no_file(board_client, private_files):
    """
    Given a title longer than the model allows
    When the document is deposited
    Then it is refused on the title, and no file is left on disk
    """
    response = deposit(board_client, title="x" * 201)

    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "title"],
            "msg": (
                "Assurez-vous que cette valeur comporte au plus 200 caractères (actuellement 201)."
            ),
        }
    ]
    assert stored_files(private_files) == []


def test_a_document_that_fails_to_record_leaves_no_file(board_member, private_files, monkeypatch):
    """
    Given a file checked and written, whose record then fails
    When the deposit is undone
    Then the file written is removed with it
    """

    def failing_save(*args, **kwargs):
        raise RuntimeError("database unreachable")

    monkeypatch.setattr(Document, "save", failing_save)
    data = DocumentUploadIn(category=DocumentCategory.INVOICE)

    with pytest.raises(RuntimeError):
        upload_document(upload(pdf()), data, board_member)

    assert stored_files(private_files) == []


# Reading the file


def test_the_file_is_shown_in_the_browser_with_its_type(board_client):
    """
    Given a deposited PDF
    When a member opens it
    Then the API sends it inline, of the type recorded, never to be sniffed nor kept in a cache
    """
    document = DocumentFactory(original_name="facture-sono.pdf")

    response = board_client.get(file_url(document.id))

    assert response.status_code == 200
    assert body(response) == PDF
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == 'inline; filename="facture-sono.pdf"'
    assert response["X-Content-Type-Options"] == "nosniff"
    assert set(response["Cache-Control"].split(", ")) == {"private", "no-store"}


def test_the_file_is_downloaded_under_its_accented_name(board_client):
    """
    Given a document whose name carries accents and a dash
    When a member downloads it
    Then the header gives the name in UTF-8, and is itself written in ASCII
    """
    document = DocumentFactory(original_name="Compte rendu — réunion du 24 sept.pdf")

    response = board_client.get(file_url(document.id), {"download": "true"})

    disposition = response["Content-Disposition"]
    assert disposition == (
        "attachment; filename*=utf-8''"
        "Compte%20rendu%20%E2%80%94%20r%C3%A9union%20du%2024%20sept.pdf"
    )
    assert disposition.encode("ascii")


def test_on_the_server_nginx_sends_the_file(board_client, settings):
    """
    Given the server, where nginx sends the private files
    When a member opens a document
    Then the API answers with the file's place in nginx's internal location, and no content
    And the same headers as in development
    """
    settings.PRIVATE_FILES_ACCEL_PREFIX = "/_private/"
    document = DocumentFactory(original_name="facture-sono.pdf")

    response = board_client.get(file_url(document.id))

    assert response.status_code == 200
    assert response.content == b""
    assert response["X-Accel-Redirect"] == f"/_private/{document.file.name}"
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == 'inline; filename="facture-sono.pdf"'
    assert set(response["Cache-Control"].split(", ")) == {"private", "no-store"}


def test_the_file_of_an_unknown_document_is_not_found(board_client):
    """
    Given no document of that id
    When a member asks for its file
    Then the API answers 404, in French
    """
    response = board_client.get(file_url(999_999))

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}


def test_any_member_reads_a_document_another_deposited(board_member):
    """
    Given a document deposited by another member of the board
    When a member opens it
    Then they get it: the board shares its documents
    """
    document = DocumentFactory(uploaded_by=BoardMemberFactory())

    assert client_of(board_member).get(file_url(document.id)).status_code == 200
