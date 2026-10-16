"""The invoices of the documents, recorded as expenses (6.2, A18)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.test.utils import CaptureQueriesContext

from documents.models import Document, DocumentCategory, DocumentSource, DocumentStatus
from tests.accounts.factories import BoardMemberFactory
from tests.documents.factories import DocumentFactory
from tests.events.factories import EventFactory
from tests.treasury.factories import IncomeFactory, LedgerEntryFactory
from treasury.models import LedgerEntry, LedgerEntryKind

pytestmark = pytest.mark.django_db

INVOICES = "/api/board/treasury/invoices"


def expense_url(document):
    return f"{INVOICES}/{document.pk}/expense"


def attach_url(document):
    return f"{INVOICES}/{document.pk}/attach"


def expense(**changes):
    """What the member types for the expense of an invoice."""
    return {
        "paid_on": "2026-09-29",
        "label": "Fête & Déco — décoration",
        "category": "decoration",
        "payment_method": "association_card",
        "advanced_by": None,
    } | changes


def send(client, url, payload):
    return client.post(url, payload, content_type="application/json")


def invoice(**fields):
    """The invoice of Fête & Déco, 147,40 €, for Halloween."""
    return DocumentFactory(
        **{
            "title": "Facture — Décoration Halloween",
            "issuer": "Fête & Déco",
            "amount": Decimal("147.40"),
            "event": EventFactory(title="Halloween des enfants"),
        }
        | fields
    )


def validated(**fields):
    return invoice(validated=True, **fields)


def messages(response):
    assert response.status_code == 422
    return {tuple(item["loc"]): item["msg"] for item in response.json()["detail"]}


# Recording the expense of an invoice


def test_a_paid_invoice_to_review_is_validated_with_its_expense(board_client, board_member):
    """
    Given the invoice of Fête & Déco, awaiting review, paid on 29 September
    When a member validates it and creates its entry
    Then the invoice is validated and paid on that day, and the expense is
    recorded on it, of its amount, supplier and event, the invoice as its receipt
    """
    document = invoice(paid_on=dt.date(2026, 9, 29))

    response = send(board_client, expense_url(document), expense())

    assert response.status_code == 200
    entry = LedgerEntry.objects.get()
    assert response.json()["status"] == "validated"
    assert response.json()["validated_by"]["id"] == board_member.id
    assert response.json()["paid_on"] == "2026-09-29"
    assert response.json()["ledger_entry"] == {
        "id": entry.id,
        "date": "2026-09-29",
        "label": "Fête & Déco — décoration",
        "created_at": DjangoJSONEncoder().default(entry.created_at),
    }
    assert (entry.kind, entry.amount, entry.supplier, entry.event, entry.receipt) == (
        LedgerEntryKind.EXPENSE,
        Decimal("147.40"),
        "Fête & Déco",
        document.event,
        Document.objects.get(),
    )
    assert (entry.category, entry.payment_method, entry.created_by) == (
        "decoration",
        "association_card",
        board_member,
    )


def test_an_invoice_to_pay_is_marked_paid_with_its_expense(board_client):
    """
    Given an invoice validated by Camille, still to pay
    When a member marks it paid on 30 September
    Then it is paid that day, still validated by Camille, and its expense
    recorded on that day
    """
    document = validated()
    reviewer = document.validated_by

    response = send(board_client, expense_url(document), expense(paid_on="2026-09-30"))

    assert response.json()["paid_on"] == "2026-09-30"
    assert response.json()["validated_by"]["id"] == reviewer.id
    assert LedgerEntry.objects.get().date == dt.date(2026, 9, 30)


def test_an_invoice_taken_over_from_the_v1_gets_its_expense_too(board_client):
    document = validated(source=DocumentSource.V1_IMPORT)

    response = send(board_client, expense_url(document), expense())

    assert response.status_code == 200
    assert LedgerEntry.objects.get().receipt_id == document.id


def test_an_advance_names_its_member_on_the_expense_of_an_invoice(board_client):
    marc = BoardMemberFactory()

    response = send(
        board_client,
        expense_url(validated()),
        expense(payment_method="advance", advanced_by=marc.id),
    )

    assert response.status_code == 200
    assert LedgerEntry.objects.get().advanced_by == marc


@pytest.mark.parametrize(
    ("changes", "errors"),
    [
        (
            {"paid_on": "2999-01-01"},
            {("body", "paid_on"): "La date ne peut pas être dans le futur."},
        ),
        (
            {"category": "bar"},
            {("body", "category"): "Choisissez une catégorie de dépense."},
        ),
        (
            {"payment_method": "advance"},
            {("body", "advanced_by"): "Choisissez le membre qui a avancé la dépense."},
        ),
        (
            {"label": " "},
            {("body", "label"): "Ce champ ne peut pas être vide."},
        ),
    ],
)
def test_the_expense_of_an_invoice_is_checked_as_any_entry(board_client, changes, errors):
    """
    Given an invoice awaiting review
    When a member creates its expense paid in the future, of a category of
    income, advanced by no one, or without a label
    Then it is refused under its field, and the invoice stays as it was
    """
    document = invoice()

    response = send(board_client, expense_url(document), expense(**changes))

    assert messages(response) == errors
    document.refresh_from_db()
    assert (document.status, document.paid_on) == (DocumentStatus.TO_REVIEW, None)
    assert not LedgerEntry.objects.exists()


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({"category": DocumentCategory.MINUTES}, "Seule une facture devient une dépense."),
        ({"amount": None}, "Indiquez le montant de la facture avant de créer sa dépense."),
        ({"amount": Decimal(0)}, "Indiquez le montant de la facture avant de créer sa dépense."),
    ],
)
def test_only_an_invoice_with_its_amount_becomes_an_expense(board_client, fields, message):
    response = send(board_client, expense_url(invoice(**fields)), expense())

    assert messages(response) == {("body",): message}


def test_an_invoice_gets_a_single_expense(board_client):
    """
    Given an invoice whose expense is recorded
    When a member records it again
    Then it is refused: the invoice has its expense
    """
    document = validated()
    send(board_client, expense_url(document), expense())

    response = send(board_client, expense_url(document), expense())

    assert messages(response) == {("body",): "Cette facture a déjà sa dépense."}
    assert LedgerEntry.objects.count() == 1


def test_recording_an_invoice_locks_it_before_anything(board_client):
    with CaptureQueriesContext(connection) as queries:
        send(board_client, expense_url(validated()), expense())

    locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
    assert len(locks) == 1
    assert Document._meta.db_table in locks[0]


# Attaching an invoice to an expense entered before


def test_an_invoice_becomes_the_receipt_of_an_expense_entered_before(board_client, board_member):
    """
    Given the drinks of the bar, entered on 12 September without their receipt,
    and their invoice, awaiting review, with no payment date
    When a member attaches the invoice to that expense
    Then the invoice is validated, paid on the expense's date, and proves it
    """
    entry = LedgerEntryFactory(date=dt.date(2026, 9, 12))
    document = invoice()

    response = send(board_client, attach_url(document), {"entry": entry.id})

    assert response.status_code == 200
    assert response.json()["status"] == "validated"
    assert response.json()["validated_by"]["id"] == board_member.id
    assert response.json()["paid_on"] == "2026-09-12"
    assert response.json()["ledger_entry"]["id"] == entry.id
    entry.refresh_from_db()
    assert entry.receipt == document


def test_an_invoice_attached_keeps_its_own_payment_date(board_client):
    entry = LedgerEntryFactory(date=dt.date(2026, 9, 12))
    document = validated(paid_on=dt.date(2026, 9, 14))

    response = send(board_client, attach_url(document), {"entry": entry.id})

    assert response.json()["paid_on"] == "2026-09-14"


@pytest.mark.parametrize(
    "entry",
    [
        lambda: IncomeFactory(),
        lambda: LedgerEntryFactory(receipt=DocumentFactory()),
        lambda: None,
    ],
)
def test_an_invoice_attaches_to_an_expense_without_receipt_only(board_client, entry):
    """
    Given an income, an expense that has its receipt, or no entry at all
    When a member attaches an invoice to it
    Then it is refused under the entry
    """
    target = entry()

    response = send(board_client, attach_url(invoice()), {"entry": target.id if target else 999999})

    assert messages(response) == {("body", "entry"): "Choisissez une dépense sans justificatif."}


def test_an_invoice_with_its_expense_is_not_attached_again(board_client):
    document = validated()
    LedgerEntryFactory(receipt=document)

    response = send(board_client, attach_url(document), {"entry": LedgerEntryFactory().id})

    assert messages(response) == {("body",): "Cette facture a déjà sa dépense."}


def test_attaching_an_invoice_locks_it_then_the_expense(board_client):
    entry = LedgerEntryFactory()

    with CaptureQueriesContext(connection) as queries:
        send(board_client, attach_url(validated()), {"entry": entry.id})

    locks = [query["sql"] for query in queries.captured_queries if "FOR UPDATE" in query["sql"]]
    assert len(locks) == 2
    assert Document._meta.db_table in locks[0]
    assert LedgerEntry._meta.db_table in locks[1]


@pytest.mark.parametrize("operation", ["expense", "attach"])
def test_an_unknown_document_is_not_found(board_client, operation):
    payload = expense() if operation == "expense" else {"entry": 1}

    response = send(board_client, f"{INVOICES}/999999/{operation}", payload)

    assert response.status_code == 404
