"""The sworn statement of a purchase whose receipt was lost (D14)."""

import datetime as dt
from decimal import Decimal
from io import BytesIO
from pathlib import Path

import pytest
from django.contrib.auth.models import Group
from django.core.serializers.json import DjangoJSONEncoder
from django.test import Client
from django.utils import timezone
from ninja_jwt.tokens import AccessToken
from pypdf import PdfReader

from documents.models import Document
from documents.services.notifications import DOCUMENT_NOTIFICATION_GROUP
from documents.services.statements import UNNAMED, statement_pdf
from tests.accounts.factories import BoardMemberFactory
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db

STATEMENTS = "/api/board/documents/statements"

PURCHASE_DATE = dt.date(2026, 10, 12)
# The moment a statement is made, in Paris time.
MADE_AT = timezone.make_aware(dt.datetime(2026, 10, 13, 14, 32))


def statement(**fields):
    """A statement as the form sends it: every key, and what it attests."""
    return {
        "supplier": "Carrefour",
        "purchase_date": "2026-10-12",
        "purchase": "Boissons et gobelets pour la buvette",
        "amount": "23.40",
        "event": None,
    } | fields


def client_of(member):
    return Client(headers={"Authorization": f"Bearer {AccessToken.for_user(member)}"})


def attest(client, **fields):
    return client.post(STATEMENTS, statement(**fields), content_type="application/json")


def text_of(content):
    """The words a PDF shows, one space apart, as a reader extracts them."""
    return " ".join(PdfReader(BytesIO(content)).pages[0].extract_text().split())


def stored_files(private_files):
    folder = Path(private_files) / "documents"
    return sorted(folder.iterdir()) if folder.exists() else []


def errors_of(response):
    return {tuple(item["loc"]): item["msg"] for item in response.json()["detail"]}


# The document


def test_a_member_attests_a_purchase_whose_receipt_was_lost(
    board_client, board_member, private_files
):
    """
    Given a board member who lost the receipt of a purchase for an event
    When they attest the purchase
    Then an invoice awaits review, made from the statement, paid on the day of the purchase
    And its file is a PDF, stored under a random name
    """
    event = EventFactory()

    response = attest(board_client, event=event.id)

    assert response.status_code == 201
    document = Document.objects.get()
    assert response.json() == {
        "id": document.id,
        "title": "Boissons et gobelets pour la buvette",
        "category": "invoice",
        "status": "to_review",
        "source": "sworn_statement",
        "original_name": "Attestation — Carrefour — 12-10-2026.pdf",
        "mime_type": "application/pdf",
        "size": document.size,
        "document_date": "2026-10-12",
        "date": "2026-10-12",
        "issuer": "Carrefour",
        "reference": "",
        "amount": "23.40",
        "due_date": None,
        "paid_on": "2026-10-12",
        "event": {"id": event.id, "title": event.title},
        "extracted": {
            "delivery_date": None,
            "items": "",
            "abstract": "",
            "decisions": [],
            "tasks": [],
            "key_date": "",
        },
        "note": "",
        "uploaded_by": {
            "id": board_member.id,
            "first_name": board_member.first_name,
            "last_name": board_member.last_name,
            "email": board_member.email,
        },
        "validated_by": None,
        "validated_at": None,
        "created_at": DjangoJSONEncoder().default(document.created_at),
    }
    [stored] = stored_files(private_files)
    assert stored.suffix == ".pdf"
    assert stored.read_bytes() == document.file.read()
    assert document.size == stored.stat().st_size


def test_the_pdf_tells_what_the_member_attested(board_client):
    """
    Given a treasurer, Camille Martin, who lost the receipt of a purchase for an event
    When they attest it
    Then the document's file is the statement of the purchase, in their name, of the day
    """
    event = EventFactory(title="Loto d’automne")

    response = attest(board_client, event=event.id)

    made = timezone.localtime(Document.objects.get().created_at)
    file = board_client.get(f"/api/board/documents/{response.json()['id']}/file")
    assert file["Content-Type"] == "application/pdf"
    text = text_of(b"".join(file.streaming_content))
    assert text.startswith("Carrefour Achat du 12/10/2026 Attestation de dépense sur l’honneur")
    assert "Je soussigné·e Camille Martin, trésorier·e du Comité des fêtes d’Ons-en-Bray" in text
    assert "Achat Boissons et gobelets pour la buvette Montant TTC 23,40 €" in text
    assert "Événement Loto d’automne" in text
    assert f"Fait le {made:%d/%m/%Y} à " in text


def test_the_statement_reads_as_the_member_attests_it():
    """
    Given a treasurer, a purchase without an event, of more than a thousand euros
    When its statement is drawn
    Then one A4 page tells the supplier, then the statement, the amount written in French
    And the file names its supplier, its maker and the purchase
    """
    member = BoardMemberFactory(first_name="Camille", last_name="Martin")
    document = Document(
        issuer="Carrefour",
        document_date=PURCHASE_DATE,
        title="Boissons et gobelets pour la buvette",
        amount=Decimal("1234.5"),
    )

    content = statement_pdf(document, member, timezone.localtime(MADE_AT))

    reader = PdfReader(BytesIO(content))
    assert len(reader.pages) == 1
    assert [round(side) for side in reader.pages[0].mediabox[2:]] == [595, 842]
    assert text_of(content) == (
        "Carrefour Achat du 12/10/2026 "
        "Attestation de dépense sur l’honneur Comité des fêtes d’Ons-en-Bray "
        "Je soussigné·e Camille Martin, trésorier·e du Comité des fêtes d’Ons-en-Bray, "
        "atteste sur l’honneur avoir payé l’achat suivant pour le compte du comité : "
        "Fournisseur Carrefour Date de l’achat 12/10/2026 "
        "Achat Boissons et gobelets pour la buvette Montant TTC 1 234,50 € "
        "Événement Fonctionnement du comité "
        "Le ticket de caisse de cet achat a été perdu : "
        "cette attestation le remplace comme justificatif. "
        "Fait le 13/10/2026 à 14 h 32, depuis l’espace du bureau, par Camille Martin."
    )
    assert reader.metadata.title == "Attestation de dépense sur l’honneur — Carrefour"
    assert reader.metadata.author == "Camille Martin"
    assert reader.metadata.subject == ("Achat du 12/10/2026 : Boissons et gobelets pour la buvette")
    assert reader.metadata.creator == "Comité des fêtes d’Ons-en-Bray"


def test_a_member_without_a_position_attests_as_one_of_the_board():
    """
    Given a board member without a position
    When their statement is drawn
    Then they attest as a member of the board
    """
    member = BoardMemberFactory(first_name="Lou", last_name="Bernard", position="")
    document = Document(
        issuer="Boulangerie", document_date=PURCHASE_DATE, title="Pain", amount=Decimal(8)
    )

    text = text_of(statement_pdf(document, member, MADE_AT))

    assert "Je soussigné·e Lou Bernard, membre du bureau du Comité des fêtes" in text


def test_the_texts_are_printed_as_typed():
    """
    Given a supplier and a purchase whose texts hold « & », « < » and « > »
    When the statement is drawn
    Then they are printed as typed, not read as markup
    """
    member = BoardMemberFactory()
    document = Document(
        issuer="Brico & Co",
        document_date=PURCHASE_DATE,
        title="Rallonges <10 m> & adaptateurs",
        amount=Decimal("12.90"),
    )

    text = text_of(statement_pdf(document, member, MADE_AT))

    assert text.startswith("Brico & Co ")
    assert "Achat Rallonges <10 m> & adaptateurs Montant TTC 12,90 €" in text


def test_a_statement_tells_the_group_like_a_deposit(
    board_client, board_member, mailoutbox, django_capture_on_commit_callbacks
):
    """
    Given a board member of the group « Notifications documents »
    When another member attests a purchase
    Then the member of the group is told a document awaits review, and the maker is not
    """
    group = Group.objects.get(name=DOCUMENT_NOTIFICATION_GROUP)
    reader = BoardMemberFactory(email="julie@example.fr")
    reader.groups.add(group)
    board_member.groups.add(group)

    with django_capture_on_commit_callbacks(execute=True):
        attest(board_client)

    [message] = mailoutbox
    assert message.to == [reader.email]
    assert message.subject == "Nouveau document à vérifier : Boissons et gobelets pour la buvette"


# Refusals


def test_a_purchase_of_today_is_attested(board_client):
    """
    Given a purchase made today
    When it is attested
    Then the statement is made
    """
    response = attest(board_client, purchase_date=timezone.localdate().isoformat())

    assert response.status_code == 201


def test_a_purchase_to_come_is_refused(board_client, private_files):
    """
    Given a purchase dated tomorrow
    When it is attested
    Then it is refused on its date, and nothing is stored
    """
    tomorrow = timezone.localdate() + dt.timedelta(days=1)

    response = attest(board_client, purchase_date=tomorrow.isoformat())

    assert response.status_code == 422
    assert errors_of(response) == {
        ("body", "purchase_date"): "La date de l’achat ne peut pas être dans le futur."
    }
    assert not Document.objects.exists()
    assert stored_files(private_files) == []


def test_an_empty_statement_is_refused_on_each_field(board_client):
    """
    Given a statement without a supplier, a purchase that is only spaces, and an amount of zero
    When it is attested
    Then each field is refused, under its own name
    """
    response = attest(board_client, supplier="", purchase="   ", amount="0")

    assert response.status_code == 422
    assert errors_of(response) == {
        ("body", "supplier"): "Ce champ ne peut pas être vide.",
        ("body", "amount"): "Indiquez un montant supérieur à zéro.",
        ("body", "purchase"): "Ce champ ne peut pas être vide.",
    }


def test_a_negative_amount_is_refused_once(board_client):
    """
    Given a statement of a negative amount
    When it is attested
    Then the amount is refused with the statement's message alone
    """
    response = attest(board_client, amount="-5")

    assert errors_of(response) == {("body", "amount"): "Indiquez un montant supérieur à zéro."}


def test_values_beyond_the_documents_limits_are_refused(board_client):
    """
    Given a supplier of 201 characters, an amount to the thousandth and an unknown event
    When they are attested
    Then each is refused as a document refuses it, under the statement's field
    """
    response = attest(board_client, supplier="x" * 201, amount="23.405", event=999999)

    assert errors_of(response) == {
        ("body", "supplier"): (
            "Assurez-vous que cette valeur comporte au plus 200 caractères (actuellement 201)."
        ),
        ("body", "amount"): "Assurez-vous qu’il n’y a pas plus de 2 chiffres après la virgule.",
        ("body", "event"): "Choisissez un événement existant.",
    }


def test_a_statement_lacking_its_keys_is_refused(board_client):
    """
    Given a statement sent without any of its fields
    When the API reads it
    Then each is refused as required
    """
    response = board_client.post(STATEMENTS, {}, content_type="application/json")

    assert response.status_code == 422
    assert errors_of(response) == {
        ("body", "payload", field): "Ce champ est obligatoire."
        for field in ("supplier", "purchase_date", "purchase", "amount", "event")
    }


def test_an_account_without_a_full_name_cannot_attest(private_files):
    """
    Given a board member whose account has a first name but no last name
    When they attest a purchase
    Then the statement is refused, as it must name its maker, and nothing is stored
    """
    member = BoardMemberFactory(first_name="Gabriel", last_name="")

    response = attest(client_of(member))

    assert response.status_code == 422
    assert errors_of(response) == {("body",): UNNAMED}
    assert not Document.objects.exists()
    assert stored_files(private_files) == []
