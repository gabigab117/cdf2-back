import datetime as dt
from decimal import Decimal

import pytest

from tests.events.factories import EventFactory
from tests.helpers import iso
from tests.treasury.factories import IncomeFactory, LedgerEntryFactory
from tests.treasury.mockup import EXPENSE, INCOME, RESULT, build_mockup
from treasury.services.results import fiscal_year_results, fiscal_years

pytestmark = pytest.mark.django_db

RESULTS = "/api/board/treasury/results"


def totals(income, expense, result, count):
    return {"income": income, "expense": expense, "result": result, "count": count}


def test_the_results_of_the_mockup(board_client, mockup_day):
    """
    Given the ledger of the mockup, on its day
    When a member reads the results of 2026
    Then the fiscal year brought in 11 490,00 € and cost 6 921,25 €, a result of
    4 568,75 €
    And each event that has entries comes the first to start first, the
    brocante bringing 3 140,00 €
    And the events without entries are left out, the general running last
    """
    events = build_mockup()

    response = board_client.get(RESULTS, {"year": 2026})

    assert response.status_code == 200
    results = response.json()
    assert results["year"] == 2026
    assert results["years"] == [2026]
    assert results["totals"] == totals(str(INCOME), str(EXPENSE), str(RESULT), 19)
    assert [
        (result["event"]["title"], result["income"], result["expense"], result["result"])
        for result in results["events"]
    ] == [
        ("Loto de printemps", "1920.00", "1040.00", "880.00"),
        ("Chasse aux œufs", "0.00", "310.00", "-310.00"),
        ("Feu de la Saint-Jean", "1480.00", "1120.00", "360.00"),
        ("Fête du 14 juillet", "2350.00", "2910.00", "-560.00"),
        ("Brocante", "4120.00", "980.00", "3140.00"),
        ("Halloween des enfants", "0.00", "195.25", "-195.25"),
    ]
    assert results["events"][4]["count"] == 5
    # As the database gives it back, in UTC.
    events["brocante"].refresh_from_db()
    assert results["events"][4]["event"] == {
        "id": events["brocante"].id,
        "title": "Brocante",
        "starts_at": iso(events["brocante"].starts_at),
    }
    assert results["general"] == totals("1620.00", "366.00", "1254.00", 5)


def test_a_fiscal_year_is_a_calendar_year(mockup_day):
    """
    Given an expense on the last day of 2025 and an income on the first of 2026
    When the results of each year are read
    Then each year counts its own entry
    """
    LedgerEntryFactory(date=dt.date(2025, 12, 31), amount=Decimal("10.00"))
    IncomeFactory(date=dt.date(2026, 1, 1), amount=Decimal("25.00"))

    last_year = fiscal_year_results(2025)
    this_year = fiscal_year_results(2026)

    assert (last_year.totals.income, last_year.totals.expense) == (Decimal(0), Decimal("10.00"))
    assert (this_year.totals.income, this_year.totals.expense) == (Decimal("25.00"), Decimal(0))
    assert this_year.years == [2026, 2025]


def test_a_year_without_entries_has_nothing_to_tell(board_client, mockup_day):
    """
    Given an event of 2027, and no entry
    When a member reads the results of 2027
    Then every total is nothing, no event comes, and the years offered are the
    current one alone
    """
    EventFactory()

    response = board_client.get(RESULTS, {"year": 2027})

    assert response.json() == {
        "year": 2027,
        "years": [2026],
        "totals": totals("0.00", "0.00", "0.00", 0),
        "events": [],
        "general": totals("0.00", "0.00", "0.00", 0),
    }


def test_the_years_offered_are_those_of_the_entries_and_the_current_one(mockup_day):
    """
    Given entries of 2024 and 2025, today in 2026
    When the fiscal years are read
    Then they are 2026, 2025 and 2024, the latest first
    """
    LedgerEntryFactory(date=dt.date(2024, 5, 1))
    LedgerEntryFactory(date=dt.date(2025, 5, 1))
    LedgerEntryFactory(date=dt.date(2025, 6, 1))

    assert fiscal_years() == [2026, 2025, 2024]


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ({}, "Ce champ est obligatoire."),
        ({"year": "deux mille"}, "Saisissez un nombre entier."),
    ],
)
def test_the_results_need_a_year(board_client, query, message):
    """
    Given no year, or a year that is no number
    When a member reads the results
    Then they are refused with a 422, in French
    """
    response = board_client.get(RESULTS, query)

    assert response.status_code == 422
    assert [item["msg"] for item in response.json()["detail"]] == [message]


def test_reading_the_results_takes_a_fixed_number_of_queries(
    board_client, mockup_day, django_assert_max_num_queries
):
    """
    Given the ledger of the mockup
    When a member reads the results of 2026
    Then the totals by event and the years take a fixed number of queries
    """
    build_mockup()

    # Authentication (2), the totals by event, the years.
    with django_assert_max_num_queries(4):
        board_client.get(RESULTS, {"year": 2026})
