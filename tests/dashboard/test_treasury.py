"""What the treasury leaves to the board, in its bell (A6, 6.2)."""

import datetime as dt
from decimal import Decimal

import pytest

from documents.models import DocumentCategory, DocumentSource
from tests.accounts.factories import BoardMemberFactory
from tests.documents.factories import DocumentFactory
from tests.treasury.factories import AdvanceFactory, IncomeFactory, LedgerEntryFactory
from treasury.models import LedgerCategory, ReimbursementMethod

pytestmark = pytest.mark.django_db

OVERVIEW = "/api/board/overview"


def pending(client):
    return client.get(OVERVIEW).json()["pending"]


def to_pay(**fields):
    """An invoice validated, which is not paid yet."""
    return DocumentFactory(validated=True, **fields)


def test_the_bell_asks_for_the_receipts_missing_the_oldest_first(board_client):
    """
    Given two expenses without their receipt, bank fees, an income, and an
    expense with its receipt
    When a member opens the bell
    Then the two expenses come, the oldest first, each with the member to ask
    """
    sophie = BoardMemberFactory(first_name="Sophie")
    LedgerEntryFactory(label="Courses goûter", date=dt.date(2026, 9, 30), created_by=sophie)
    LedgerEntryFactory(label="Courses buvette", date=dt.date(2026, 9, 12), created_by=sophie)
    LedgerEntryFactory(label="Frais", category=LedgerCategory.BANK_FEES)
    IncomeFactory(label="Buvette")
    LedgerEntryFactory(label="Assurance", receipt=DocumentFactory())

    receipts = pending(board_client)["receipts"]

    assert receipts["count"] == 2
    assert [item["label"] for item in receipts["items"]] == ["Courses buvette", "Courses goûter"]
    assert receipts["items"][0]["contact"]["first_name"] == "Sophie"


def test_the_bell_lists_ten_receipts_missing_at_most(board_client):
    LedgerEntryFactory.create_batch(12)

    receipts = pending(board_client)["receipts"]

    assert (receipts["count"], len(receipts["items"])) == (12, 10)


def test_the_bell_lists_the_invoices_to_pay_the_first_due_first(board_client, mockup_day):
    """
    Given invoices to pay, due on 28 October, past due on 20 September, and
    without due date
    And an invoice paid, one awaiting review, one recorded already, one taken
    over from the v1, and an order, none to pay
    When a member opens the bell
    Then the three invoices to pay come by due date, the one past due told so,
    the one without due date last
    """
    to_pay(
        title="Location sono",
        issuer="Animation 60",
        amount=Decimal("380.00"),
        due_date=dt.date(2026, 10, 28),
    )
    to_pay(title="Chalets", due_date=dt.date(2026, 9, 20))
    to_pay(title="Sans échéance")
    to_pay(title="Payée", paid_on=dt.date(2026, 9, 1))
    DocumentFactory(title="À vérifier")
    LedgerEntryFactory(receipt=to_pay(title="Enregistrée"))
    to_pay(title="Reprise", source=DocumentSource.V1_IMPORT)
    to_pay(title="Commande", category=DocumentCategory.ORDER)

    invoices = pending(board_client)["invoices"]

    assert invoices["count"] == 3
    assert [(item["title"], item["overdue"]) for item in invoices["items"]] == [
        ("Chalets", True),
        ("Location sono", False),
        ("Sans échéance", False),
    ]
    assert invoices["items"][1] == {
        "id": invoices["items"][1]["id"],
        "title": "Location sono",
        "issuer": "Animation 60",
        "amount": "380.00",
        "due_date": "2026-10-28",
        "overdue": False,
    }


def test_the_bell_counts_what_the_treasury_leaves_to_do(board_client):
    """
    Given a document to review, an expense missing its receipt and an invoice to pay
    When a member opens the bell
    Then it counts the three
    """
    DocumentFactory()
    LedgerEntryFactory()
    to_pay()

    assert pending(board_client)["total"] == 3


def test_the_bell_lists_the_advances_owed_the_oldest_first(board_client):
    """
    Given advances of Marc owed since 12 and 30 September, and one reimbursed
    When a member opens the bell
    Then the two advances owed come, the oldest first, with what they add up to
    """
    AdvanceFactory(label="Goûter", date=dt.date(2026, 9, 30), amount=Decimal("47.85"))
    AdvanceFactory(label="Buvette", date=dt.date(2026, 9, 12), amount=Decimal("286.30"))
    AdvanceFactory(
        label="Remboursée",
        reimbursed_on=dt.date(2026, 9, 20),
        reimbursement_method=ReimbursementMethod.CASH,
    )

    advances = pending(board_client)["advances"]

    assert (advances["count"], advances["total"]) == (2, "334.15")
    assert [item["label"] for item in advances["items"]] == ["Buvette", "Goûter"]
