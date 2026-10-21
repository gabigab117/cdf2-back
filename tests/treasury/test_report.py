"""The report of a fiscal year for the general meeting (6.6)."""

import datetime as dt

import pytest

from tests.documents.factories import DocumentFactory
from tests.treasury.factories import LedgerEntryFactory
from tests.treasury.mockup import EXPENSE, INCOME, RESULT, build_mockup
from tests.treasury.scenario import reference_scenario

pytestmark = pytest.mark.django_db

REPORT = "/api/board/treasury/report"


def test_the_report_of_the_mockup(board_client, mockup_day):
    """
    Given the ledger of the mockup, no receipt joined
    When a member reads the report of 2026
    Then it tells the totals and results of the year, what each category
    brought in or cost in the order of the form, and the expenses missing
    their receipt, the oldest first, bank fees left out
    """
    build_mockup()

    report = board_client.get(REPORT, {"year": 2026}).json()

    assert report["year"] == 2026
    assert (
        report["totals"]["income"],
        report["totals"]["expense"],
        report["totals"]["result"],
    ) == (
        str(INCOME),
        str(EXPENSE),
        str(RESULT),
    )
    assert [event["event"]["title"] for event in report["events"]][-1] == "Halloween des enfants"
    assert report["general"]["result"] == "1254.00"
    assert [(row["category"], row["total"]) for row in report["income_categories"]] == [
        ("bar", "5692.50"),
        ("pitches", "2257.50"),
        ("tickets", "1920.00"),
        ("grant", "1500.00"),
        ("membership_fees", "120.00"),
    ]
    assert [(row["category"], row["total"]) for row in report["expense_categories"]] == [
        ("food", "357.85"),
        ("drinks", "286.30"),
        ("equipment_rental", "95.00"),
        ("decoration", "147.40"),
        ("prizes", "1040.00"),
        ("insurance", "312.00"),
        ("bank_fees", "54.00"),
        ("misc", "4628.70"),
    ]
    missing = report["missing_receipts"]
    assert len(missing) == 10
    assert (missing[0]["label"], missing[-1]["label"]) == ("Lots du loto", "Courses goûter")


def test_the_report_keeps_the_receipts_missing_of_its_year(board_client):
    LedgerEntryFactory(label="Réveillon", date=dt.date(2025, 12, 31))
    LedgerEntryFactory(label="Galette", date=dt.date(2026, 1, 1))
    LedgerEntryFactory(label="Assurance", date=dt.date(2026, 2, 1), receipt=DocumentFactory())

    report = board_client.get(REPORT, {"year": 2026}).json()

    assert [entry["label"] for entry in report["missing_receipts"]] == ["Galette"]
    assert [row["count"] for row in report["expense_categories"]] == [2]


def test_a_year_without_entries_has_an_empty_report(board_client):
    report = board_client.get(REPORT, {"year": 2027}).json()

    assert report["totals"] == {"income": "0.00", "expense": "0.00", "result": "0.00", "count": 0}
    assert (report["events"], report["income_categories"], report["expense_categories"]) == (
        [],
        [],
        [],
    )
    assert report["missing_receipts"] == []


def test_reading_the_report_takes_a_fixed_number_of_queries(
    board_client, mockup_day, django_assert_max_num_queries
):
    build_mockup()

    # Authentication (2), the totals by event, the years, the categories, the
    # receipts missing with their links, then the management of the year: the
    # items, their movements, the expenses that paid a purchase, the bar income.
    with django_assert_max_num_queries(10):
        board_client.get(REPORT, {"year": 2026})


def test_the_report_tells_the_stock_and_the_management_of_its_year(board_client, mockup_day):
    """
    Given the reference scenario of the brocante (D16)
    When a member reads the report of 2026
    Then it tells the stock, worth nothing on 1 January and 22,67 € today, the
    adjusted result of 32,67 €, the management result of the brocante and of
    the general running, and the 1,13 € of losses
    """
    reference_scenario()

    management = board_client.get(REPORT, {"year": 2026}).json()["management"]

    assert management["totals"] == {
        "result": "10.00",
        "opening_value": "0.00",
        "closing_value": "22.67",
        "stock_change": "22.67",
        "adjusted_result": "32.67",
        "management_result": "18.27",
    }
    assert [(row["event"]["title"], row["management_result"]) for row in management["events"]] == [
        ("Brocante", "19.40")
    ]
    assert management["general"]["management_result"] == "-1.13"
    assert management["stock"]["losses"]["total"] == "1.13"
