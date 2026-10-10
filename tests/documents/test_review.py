"""The board's documents once deposited: listed, searched, read, corrected,
validated and deleted.
"""

import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from documents.models import Document, DocumentCategory, DocumentStatus
from tasks.models import Task
from tests.accounts.factories import BoardMemberFactory, UserFactory
from tests.documents.factories import DocumentFactory
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db

DOCUMENTS = "/api/board/documents"


def document_url(document_id):
    return f"{DOCUMENTS}/{document_id}"


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


def send(client, method, path, payload=None):
    return getattr(client, method)(path, payload, content_type="application/json")


def listed_titles(client, **params):
    return [item["title"] for item in client.get(DOCUMENTS, params).json()["items"]]


def deposited_on(document, day):
    """Date a document's deposit, its creation time being set by the database."""
    moment = timezone.make_aware(dt.datetime.combine(day, dt.time(10)))
    Document.objects.filter(pk=document.pk).update(created_at=moment)


def extracted(**keys):
    """The extracted data of a correction, whole: every key, empty unless given."""
    return {
        "delivery_date": None,
        "items": "",
        "abstract": "",
        "decisions": [],
        "tasks": [],
        "key_date": "",
    } | keys


def correction(**changes):
    """The JSON body of a document corrected whole, as the « Corriger » form sends it."""
    return {
        "category": "invoice",
        "title": "Facture — Location sono",
        "event": None,
        "document_date": "2026-09-28",
        "issuer": "Animation 60",
        "reference": "F-2026-0418",
        "amount": "380.00",
        "due_date": "2026-10-28",
        "paid_on": None,
        "note": "",
        "extracted": extracted(),
    } | changes


# List


def test_the_documents_come_by_date_the_latest_first(board_client):
    """
    Given an invoice dated 28 September, minutes without a date deposited on
    1 October, and an order dated 25 September deposited after them
    When a member lists the documents
    Then they come by their date, the document's own or else its deposit's
    """
    invoice = DocumentFactory(document_date=dt.date(2026, 9, 28))
    minutes = DocumentFactory(category=DocumentCategory.MINUTES)
    deposited_on(minutes, dt.date(2026, 10, 1))
    order = DocumentFactory(category=DocumentCategory.ORDER, document_date=dt.date(2026, 9, 25))

    assert listed_titles(board_client) == [minutes.title, invoice.title, order.title]


def test_a_listed_document_holds_what_its_row_shows(board_client):
    """
    Given an invoice of an event, of 380 €, awaiting review
    When a member lists the documents
    Then its row holds its title, category, status, event, amount and date
    """
    event = EventFactory(title="Halloween des enfants")
    document = DocumentFactory(
        event=event, amount=Decimal("380.00"), document_date=dt.date(2026, 9, 28)
    )

    response = board_client.get(DOCUMENTS)

    assert response.json() == {
        "items": [
            {
                "id": document.id,
                "title": document.title,
                "category": "invoice",
                "status": "to_review",
                "event": {"id": event.id, "title": "Halloween des enfants"},
                "amount": "380.00",
                "date": "2026-09-28",
            }
        ],
        "count": 1,
    }


def test_listing_the_documents_reads_their_events_at_once(
    board_client, django_assert_max_num_queries
):
    """
    Given five documents, each of its own event
    When a member lists them
    Then the events come with the documents, in a fixed number of queries
    """
    for event in EventFactory.create_batch(5):
        DocumentFactory(event=event)

    # Authentication (2), the count of documents, the page with their events.
    with django_assert_max_num_queries(4):
        board_client.get(DOCUMENTS)


@pytest.mark.parametrize(
    ("search", "found"),
    [
        ("animation", "Facture — Location sono"),
        ("F-2026", "Facture — Location sono"),
        ("380,00", "Facture — Location sono"),
        ("380", "Facture — Location sono"),
        ("halloween", "Facture — Location sono"),
        ("défilé", "Compte rendu — Réunion du 24 sept."),
        ("BUDGET BONBONS", "Compte rendu — Réunion du 24 sept."),
        ("gobelets", "Bon de commande — Bonbons"),
        ("15 h 30", "Arrêté municipal — Cortège"),
        ("arrete", "Arrêté municipal — Cortège"),
        ("chèque", "Relevé de compte"),
    ],
)
def test_the_search_finds_a_word_anywhere_in_a_document(board_client, search, found):
    """
    Given an invoice of Halloween, minutes, an order, a municipal order and a
    statement with a remark
    When a member searches for a supplier, a number, an amount, an event, a word
    of the minutes, an item, a key date, a file name or a remark
    Then the search finds the document holding it, whatever the case
    """
    DocumentFactory(
        title="Facture — Location sono",
        issuer="Animation 60",
        reference="F-2026-0418",
        amount=Decimal("380.00"),
        event=EventFactory(title="Halloween des enfants"),
    )
    DocumentFactory(
        title="Compte rendu — Réunion du 24 sept.",
        category=DocumentCategory.MINUTES,
        extracted={
            "abstract": "Parcours du défilé validé.",
            "decisions": ["Budget bonbons : 250 €."],
        },
    )
    DocumentFactory(
        title="Bon de commande — Bonbons",
        category=DocumentCategory.ORDER,
        extracted={"items": "Bonbons assortis, gobelets"},
    )
    DocumentFactory(
        title="Arrêté municipal — Cortège",
        category=DocumentCategory.MISC,
        original_name="arrete-2026-047.pdf",
        extracted={"key_date": "31 oct. · 15 h 30"},
    )
    DocumentFactory(title="Relevé de compte", category=DocumentCategory.MISC, note="Un chèque.")

    assert listed_titles(board_client, search=search) == [found]


def test_the_list_keeps_a_category_a_status_or_an_event(board_client):
    """
    Given an invoice of Halloween validated, an invoice to review, and minutes
    When a member lists the invoices, the documents to review, then Halloween's
    Then each list keeps those alone
    """
    halloween = EventFactory()
    validated = DocumentFactory(
        event=halloween, status=DocumentStatus.VALIDATED, validated_at=timezone.now()
    )
    to_review = DocumentFactory()
    minutes = DocumentFactory(category=DocumentCategory.MINUTES)

    assert set(listed_titles(board_client, category="invoice")) == {
        validated.title,
        to_review.title,
    }
    assert set(listed_titles(board_client, status="to_review")) == {
        to_review.title,
        minutes.title,
    }
    assert listed_titles(board_client, event=halloween.id) == [validated.title]


# Counts


def test_the_counts_follow_the_search_whatever_the_category(board_client):
    """
    Given two invoices and an order of Halloween, and minutes of the loto
    When a member counts the documents of a search for Halloween, the invoices shown
    Then the counts hold every category of the search, the chosen one aside
    """
    halloween = EventFactory(title="Halloween des enfants")
    DocumentFactory.create_batch(2, event=halloween)
    DocumentFactory(event=halloween, category=DocumentCategory.ORDER)
    DocumentFactory(event=EventFactory(title="Loto"), category=DocumentCategory.MINUTES)

    response = board_client.get(
        f"{DOCUMENTS}/counts", {"search": "halloween", "category": "invoice"}
    )

    assert response.status_code == 200
    assert response.json() == {"total": 3, "invoice": 2, "order": 1, "minutes": 0, "misc": 0}


# Reading


def test_a_member_reads_a_document_with_what_belongs_to_its_kind(board_client):
    """
    Given minutes listing a decision and a task, validated by a member
    When a member reads them
    Then the document holds them, the keys of another kind left empty
    """
    member = BoardMemberFactory()
    minutes = DocumentFactory(
        category=DocumentCategory.MINUTES,
        status=DocumentStatus.VALIDATED,
        validated_by=member,
        validated_at=timezone.now(),
        extracted={
            "abstract": "Réunion consacrée à Halloween.",
            "decisions": ["Budget bonbons : 250 €."],
            "tasks": [{"title": "Valider le devis sono", "assignee": member.id}],
        },
    )

    response = board_client.get(document_url(minutes.id))

    assert response.status_code == 200
    assert response.json()["extracted"] == {
        "delivery_date": None,
        "items": "",
        "abstract": "Réunion consacrée à Halloween.",
        "decisions": ["Budget bonbons : 250 €."],
        "tasks": [{"title": "Valider le devis sono", "assignee": member.id}],
        "key_date": "",
    }
    assert response.json()["validated_by"] == member_json(member)
    assert response.json()["validated_at"] == iso(minutes.validated_at)


def test_an_unknown_document_is_not_found(board_client):
    """
    Given no document of that id
    When a member reads, corrects, validates or deletes it
    Then the API answers 404, in French
    """
    for method, path, payload in [
        ("get", document_url(999_999), None),
        ("put", document_url(999_999), correction()),
        ("post", f"{document_url(999_999)}/validate", None),
        ("delete", document_url(999_999), None),
    ]:
        response = send(board_client, method, path, payload)
        assert response.status_code == 404, method
        assert response.json() == {"detail": "Introuvable."}


# Correction


def test_a_member_corrects_an_invoice(board_client):
    """
    Given an invoice awaiting review
    When a member corrects its fields and links it to an event
    Then the invoice holds them, and still awaits review
    """
    document = DocumentFactory()
    event = EventFactory()

    response = send(board_client, "put", document_url(document.id), correction(event=event.id))

    assert response.status_code == 200
    body = response.json()
    assert {key: body[key] for key in ("issuer", "reference", "amount", "due_date", "status")} == {
        "issuer": "Animation 60",
        "reference": "F-2026-0418",
        "amount": "380.00",
        "due_date": "2026-10-28",
        "status": "to_review",
    }
    assert body["event"]["id"] == event.id
    assert body["date"] == "2026-09-28"


def test_a_correction_keeps_what_belongs_to_the_new_kind_alone(board_client):
    """
    Given minutes, corrected into an order with every extracted key filled
    When the correction is recorded
    Then the order keeps its delivery date and items, and loses the abstract,
    the decisions, the tasks and the key date
    """
    document = DocumentFactory(category=DocumentCategory.MINUTES)
    keys = extracted(
        delivery_date="2026-10-27",
        items="Bonbons assortis 12 kg",
        abstract="Réunion",
        decisions=["Budget : 250 €"],
        tasks=[{"title": "Commander", "assignee": None}],
        key_date="31 oct.",
    )

    send(
        board_client, "put", document_url(document.id), correction(category="order", extracted=keys)
    )

    document.refresh_from_db()
    assert document.extracted == {"delivery_date": "2026-10-27", "items": "Bonbons assortis 12 kg"}


def test_a_validated_document_stays_validated_once_corrected(board_client):
    """
    Given an invoice validated, then paid
    When a member records the day it was paid
    Then the invoice holds it, and stays validated
    """
    document = DocumentFactory(status=DocumentStatus.VALIDATED, validated_at=timezone.now())

    response = send(
        board_client, "put", document_url(document.id), correction(paid_on="2026-09-29")
    )

    assert (response.json()["paid_on"], response.json()["status"]) == ("2026-09-29", "validated")


def test_a_faulty_correction_is_refused_in_french_under_its_field(board_client):
    """
    Given an amount typed as words, then one of three decimals, then an unknown event
    When the corrections are sent
    Then each is refused under its field, in French
    """
    document = DocumentFactory()

    def errors(**changes):
        response = send(board_client, "put", document_url(document.id), correction(**changes))
        return [(error["loc"], error["msg"]) for error in response.json()["detail"]]

    assert errors(amount="trois cents") == [(["body", "payload", "amount"], "Saisissez un nombre.")]
    assert errors(amount="380.005") == [
        (["body", "amount"], "Assurez-vous qu’il n’y a pas plus de 2 chiffres après la virgule.")
    ]
    assert errors(event=999_999) == [(["body", "event"], "Choisissez un événement existant.")]


def test_the_tasks_of_minutes_are_checked_as_they_are_written(board_client):
    """
    Given minutes listing a task without a title, then a task assigned to an
    account outside the board
    When the corrections are sent
    Then each is refused under the field of its task
    """
    document = DocumentFactory(category=DocumentCategory.MINUTES)

    def errors(task):
        payload = correction(category="minutes", extracted=extracted(tasks=[task]))
        response = send(board_client, "put", document_url(document.id), payload)
        return [(error["loc"], error["msg"]) for error in response.json()["detail"]]

    assert errors({"title": "", "assignee": None}) == [
        (["body", "extracted", "tasks", 0, "title"], "Ce champ ne peut pas être vide.")
    ]
    assert errors({"title": "Relancer", "assignee": UserFactory().id}) == [
        (["body", "extracted", "tasks", 0, "assignee"], "Choisissez un membre du bureau.")
    ]


# Validation


def test_a_member_validates_a_document(board_client, board_member):
    """
    Given an invoice awaiting review
    When a member validates it
    Then it is validated, by that member, now
    """
    document = DocumentFactory()

    response = board_client.post(f"{document_url(document.id)}/validate")

    assert response.status_code == 200
    document.refresh_from_db()
    assert response.json()["status"] == "validated"
    assert response.json()["validated_by"] == member_json(board_member)
    assert response.json()["validated_at"] == iso(document.validated_at)


def test_a_document_is_validated_once(board_client):
    """
    Given a document already validated
    When a member validates it again
    Then the API refuses, in French
    """
    document = DocumentFactory(status=DocumentStatus.VALIDATED, validated_at=timezone.now())

    response = board_client.post(f"{document_url(document.id)}/validate")

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"type": "validation_error", "loc": ["body"], "msg": "Ce document est déjà validé."}
    ]


def test_validated_minutes_create_their_tasks_on_their_event(board_client, board_member):
    """
    Given minutes of Halloween listing two tasks, one assigned
    When a member validates them
    Then both tasks are created on Halloween, by that member, open
    """
    halloween = EventFactory()
    assignee = BoardMemberFactory()
    minutes = DocumentFactory(
        category=DocumentCategory.MINUTES,
        event=halloween,
        extracted={
            "tasks": [
                {"title": "Valider le devis sono", "assignee": assignee.id},
                {"title": "Trouver 2 bénévoles", "assignee": None},
            ]
        },
    )

    board_client.post(f"{document_url(minutes.id)}/validate")

    assert list(
        Task.objects.order_by("pk").values_list("event", "title", "assignee", "created_by")
    ) == [
        (halloween.id, "Valider le devis sono", assignee.id, board_member.id),
        (halloween.id, "Trouver 2 bénévoles", None, board_member.id),
    ]
    assert not Task.objects.filter(done_at__isnull=False).exists()


def test_minutes_without_an_event_create_general_tasks(board_client):
    """
    Given the minutes of a general meeting, of no event, listing a task
    When a member validates them
    Then the task is a general one (D10)
    """
    minutes = DocumentFactory(
        category=DocumentCategory.MINUTES,
        extracted={"tasks": [{"title": "Déposer le compte rendu", "assignee": None}]},
    )

    board_client.post(f"{document_url(minutes.id)}/validate")

    assert list(Task.objects.values_list("event", "title")) == [(None, "Déposer le compte rendu")]


def test_minutes_whose_task_is_refused_stay_to_review(board_client):
    """
    Given minutes listing a valid task, then one assigned to a member who has
    left the board since they were written
    When a member validates them
    Then nothing is created, the minutes stay to review, and the error is
    located on the second task
    """
    former = BoardMemberFactory()
    minutes = DocumentFactory(
        category=DocumentCategory.MINUTES,
        extracted={
            "tasks": [
                {"title": "Valider le devis sono", "assignee": None},
                {"title": "Relancer les commerçants", "assignee": former.id},
            ]
        },
    )
    former.groups.clear()

    response = board_client.post(f"{document_url(minutes.id)}/validate")

    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "extracted", "tasks", 1, "assignee"],
            "msg": "Choisissez un membre du bureau.",
        }
    ]
    assert not Task.objects.exists()
    minutes.refresh_from_db()
    assert minutes.status == DocumentStatus.TO_REVIEW


# Deletion


def test_a_member_deletes_a_document_and_its_file(
    board_client, private_files, django_capture_on_commit_callbacks
):
    """
    Given a deposited document
    When a member deletes it
    Then the document is gone, and its file too once the deletion is done
    """
    document = DocumentFactory()
    stored = Path(private_files) / document.file.name
    assert stored.exists()

    with django_capture_on_commit_callbacks(execute=True):
        response = board_client.delete(document_url(document.id))

    assert response.status_code == 204
    assert not Document.objects.exists()
    assert not stored.exists()
