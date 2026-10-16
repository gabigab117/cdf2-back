"""The receipt of an entry, joined from the treasury (6.2)."""

import datetime as dt
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group
from django.db import DatabaseError

from documents.models import Document, DocumentCategory, DocumentStatus
from documents.services.notifications import DOCUMENT_NOTIFICATION_GROUP
from tests.accounts.factories import BoardMemberFactory
from tests.documents.factories import DocumentFactory
from tests.documents.samples import pdf, upload
from tests.events.factories import EventFactory
from tests.treasury.factories import AdvanceFactory, IncomeFactory, LedgerEntryFactory
from treasury.models import LedgerCategory, LedgerEntry
from treasury.schemas import NewLedgerEntryIn
from treasury.services.entries import record_entry

pytestmark = pytest.mark.django_db

ENTRIES = "/api/board/treasury/entries"


def form(**changes):
    return {
        "date": "2026-09-12",
        "kind": "expense",
        "label": "Courses buvette",
        "amount": "286.30",
        "category": "drinks",
        "payment_method": "association_card",
    } | changes


def receipt_url(entry):
    return f"{ENTRIES}/{entry.pk}/receipt"


def stored(private_files):
    """The files written to the private folder."""
    return [path for path in private_files.rglob("*") if path.is_file()]


def states(client, **filters):
    entries = client.get(ENTRIES, filters).json()["items"]
    return {entry["label"]: entry["receipt_state"] for entry in entries}


# Recorded with the entry


def test_a_member_records_an_expense_with_its_receipt(board_client, board_member):
    """
    Given the ticket of the drinks bought for the brocante's bar
    When a member records the expense with it
    Then the ticket is filed as an invoice, validated, paid on the expense's
    date, told by the expense's fields, and proves the expense
    """
    brocante = EventFactory(title="Brocante")

    response = board_client.post(
        ENTRIES,
        form(event=brocante.id, supplier="Supermarché", file=upload(pdf("Ticket"), "ticket.pdf")),
    )

    assert response.status_code == 201
    document = Document.objects.get()
    assert response.json()["receipt"] == {
        "id": document.id,
        "title": "Courses buvette",
        "original_name": "ticket.pdf",
        "size": document.size,
    }
    assert response.json()["receipt_state"] == "attached"
    assert (document.category, document.status, document.validated_by) == (
        DocumentCategory.INVOICE,
        DocumentStatus.VALIDATED,
        board_member,
    )
    assert (document.issuer, document.document_date, document.paid_on, document.event) == (
        "Supermarché",
        dt.date(2026, 9, 12),
        dt.date(2026, 9, 12),
        brocante,
    )
    assert str(document.amount) == "286.30"
    assert LedgerEntry.objects.get().receipt == document


def test_the_receipt_of_an_income_is_filed_with_the_misc_documents(board_client):
    """
    Given the letter of the municipality's grant
    When a member records the grant with it
    Then the letter is a document « Divers », which no invoice pays
    """
    response = board_client.post(
        ENTRIES,
        form(
            kind="income", label="Subvention", category="grant", amount="1500", file=upload(pdf())
        ),
    )

    assert response.status_code == 201
    document = Document.objects.get()
    assert (document.category, document.paid_on) == (DocumentCategory.MISC, None)


def test_a_file_the_documents_refuse_records_no_entry(board_client, private_files):
    """
    Given a text file
    When a member records an expense with it
    Then the file is refused under its field, and neither the entry nor a file
    is kept
    """
    response = board_client.post(ENTRIES, form(file=upload(b"Courses", "ticket.txt")))

    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [["body", "file"]]
    assert not LedgerEntry.objects.exists()
    assert stored(private_files) == []


def test_a_file_deposited_already_is_refused_under_its_field(board_client):
    """
    Given a ticket deposited among the documents already
    When a member records an expense with the same file
    Then the file is refused, and no entry is written
    """
    board_client.post(ENTRIES, form(file=upload(pdf("Ticket"))))

    response = board_client.post(ENTRIES, form(label="Encore", file=upload(pdf("Ticket"))))

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "file"],
            "msg": "Ce fichier a déjà été déposé.",
        }
    ]
    assert LedgerEntry.objects.count() == 1


def test_an_entry_refused_leaves_its_file_unread(board_client, private_files):
    """
    Given an expense without a label
    When a member records it with its ticket
    Then the label is refused, and no document nor file is kept
    """
    response = board_client.post(ENTRIES, form(label=" ", file=upload(pdf())))

    assert response.status_code == 422
    assert not Document.objects.exists()
    assert stored(private_files) == []


def test_a_receipt_whose_link_fails_leaves_no_file(board_member, private_files):
    """
    Given an expense and its ticket
    When the link of the ticket to the expense fails in the database
    Then nothing is written: neither the entry, the document, nor the file
    """
    save = LedgerEntry.save

    def failing(entry, *args, **kwargs):
        if kwargs.get("update_fields") == ["receipt"]:
            raise DatabaseError("lost connection")
        save(entry, *args, **kwargs)

    data = NewLedgerEntryIn(**form(amount="286.30"))
    with patch.object(LedgerEntry, "save", failing), pytest.raises(DatabaseError):
        record_entry(data, board_member, upload(pdf()))

    assert not LedgerEntry.objects.exists()
    assert not Document.objects.exists()
    assert stored(private_files) == []


def test_the_board_is_told_of_a_receipt_validated_as_it_arrives(
    board_client, mailoutbox, django_capture_on_commit_callbacks
):
    """
    Given a member of the group that hears of each document deposited
    When an expense is recorded with its ticket
    Then they are told of the receipt, to see rather than to review
    """
    julie = BoardMemberFactory(email="julie@example.fr")
    julie.groups.add(Group.objects.get(name=DOCUMENT_NOTIFICATION_GROUP))

    with django_capture_on_commit_callbacks(execute=True):
        board_client.post(ENTRIES, form(file=upload(pdf())))

    [message] = mailoutbox
    assert message.subject == "Nouveau justificatif : Courses buvette"
    assert "Pour le voir (la page demande de se connecter) :" in message.body


# Joined afterwards


def test_a_member_joins_the_receipt_found_afterwards(board_client):
    """
    Given an expense recorded without its ticket
    When a member joins the ticket
    Then the expense has its receipt
    """
    entry = LedgerEntryFactory()

    response = board_client.post(receipt_url(entry), {"file": upload(pdf())})

    assert response.status_code == 200
    assert response.json()["receipt_state"] == "attached"
    assert LedgerEntry.objects.get().receipt == Document.objects.get()


def test_a_second_receipt_is_refused(board_client, private_files):
    """
    Given an expense that has its receipt
    When a member joins another one
    Then it is refused under the file, and no document nor file is added
    """
    entry = LedgerEntryFactory(receipt=DocumentFactory())

    response = board_client.post(receipt_url(entry), {"file": upload(pdf("Autre"))})

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "file"],
            "msg": "Cette ligne a déjà son justificatif.",
        }
    ]
    assert Document.objects.count() == 1
    # The first receipt's file alone.
    assert len(stored(private_files)) == 1


def test_a_receipt_needs_its_file(board_client):
    response = board_client.post(receipt_url(LedgerEntryFactory()))

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"type": "missing", "loc": ["file", "file"], "msg": "Ce champ est obligatoire."}
    ]


def test_the_receipt_of_an_unknown_entry_is_not_found(board_client):
    response = board_client.post(f"{ENTRIES}/999999/receipt", {"file": upload(pdf())})

    assert response.status_code == 404


# Where a receipt stands


def test_each_entry_tells_where_its_receipt_stands(board_client):
    """
    Given an expense with its receipt, one without, bank fees and an income
    When a member lists the journal
    Then the first is « joint », the second « manquant », the others « sans objet »
    """
    LedgerEntryFactory(label="Assurance", receipt=DocumentFactory())
    LedgerEntryFactory(label="Courses")
    LedgerEntryFactory(label="Frais", category=LedgerCategory.BANK_FEES)
    IncomeFactory(label="Buvette")

    assert states(board_client) == {
        "Assurance": "attached",
        "Courses": "missing",
        "Frais": "not_required",
        "Buvette": "not_required",
    }


def test_an_income_may_have_a_receipt_too(board_client):
    IncomeFactory(label="Subvention", receipt=DocumentFactory())

    assert states(board_client) == {"Subvention": "attached"}


def test_the_journal_keeps_every_year_s_receipts_missing(board_client):
    """
    Given expenses of 2025 and 2026 without their receipt, and one with it
    When a member lists the journal's missing receipts
    Then both expenses missing theirs come, whatever their year
    """
    LedgerEntryFactory(label="Réveillon", date=dt.date(2025, 12, 31))
    LedgerEntryFactory(label="Galette", date=dt.date(2026, 1, 1))
    LedgerEntryFactory(label="Assurance", receipt=DocumentFactory())

    assert set(states(board_client, receipt_state="missing")) == {"Réveillon", "Galette"}


def test_the_member_to_ask_is_who_advanced_or_else_who_recorded(board_client):
    """
    Given an advance of Marc recorded by Sophie, an expense recorded by Sophie,
    and an advance whose member's account was deleted
    When a member lists the journal
    Then Marc is asked for the advance, Sophie for the others
    """
    sophie = BoardMemberFactory(first_name="Sophie")
    marc = BoardMemberFactory(first_name="Marc")
    AdvanceFactory(label="Avance", advanced_by=marc, created_by=sophie)
    LedgerEntryFactory(label="Carte", created_by=sophie)
    gone = AdvanceFactory(label="Ancien", created_by=sophie)
    gone.advanced_by.delete()

    entries = board_client.get(ENTRIES).json()["items"]

    assert {entry["label"]: entry["contact"]["first_name"] for entry in entries} == {
        "Avance": "Marc",
        "Carte": "Sophie",
        "Ancien": "Sophie",
    }
