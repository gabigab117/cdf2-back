"""The loans on the dashboard, in the bell and on an event's page (card 5.8)."""

import datetime as dt

import pytest
from django.utils import timezone

from equipment.models import LoanStatus
from tests.documents.factories import DocumentFactory
from tests.equipment.factories import (
    CommitteeLoanFactory,
    EquipmentFactory,
    LoanFactory,
    LoanLineFactory,
    lend,
)
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db

OVERVIEW = "/api/board/overview"


def ahead(days):
    return timezone.localdate() + dt.timedelta(days=days)


def out(**fields):
    return {"status": LoanStatus.OUT, **fields}


@pytest.fixture
def marquees():
    return EquipmentFactory(name="Barnums 3 × 3 m", total_quantity=40)


@pytest.fixture
def board(marquees):
    """A loan of each state, around today."""
    return {
        "overdue": lend(marquees, 1, ahead(-6), ahead(-2), **out(borrower_name="Tennis")),
        "late_checkout": lend(marquees, 1, ahead(-1), ahead(2), borrower_name="Pétanque"),
        "out": lend(marquees, 2, ahead(-1), ahead(1), **out(borrower_name="École du village")),
        "to_prepare": lend(marquees, 1, ahead(2), ahead(3), borrower_name="M. Petit"),
        "last_day": lend(marquees, 1, ahead(13), ahead(14), borrower_name="Club de football"),
        "beyond": lend(marquees, 1, ahead(14), ahead(15), borrower_name="Judo club"),
        "out_beyond": lend(marquees, 1, ahead(-1), ahead(14), **out(borrower_name="Mairie")),
        "committee": CommitteeLoanFactory(start_date=ahead(3), end_date=ahead(5)),
        "returned": lend(
            marquees,
            1,
            ahead(-5),
            ahead(-3),
            status=LoanStatus.RETURNED,
            returned_at=timezone.now(),
            borrower_name="Parents d’élèves",
        ),
        "cancelled": lend(
            marquees, 1, ahead(4), ahead(5), status=LoanStatus.CANCELLED, borrower_name="Basket"
        ),
    }


def brief(loan, state):
    """A loan as a line of a list names it."""
    return {
        "id": loan.id,
        "number": loan.number,
        "display_name": loan.display_name,
        "purpose": loan.purpose,
        "borrower_type": loan.borrower_type,
        "state": state,
        "start_date": loan.start_date.isoformat(),
        "end_date": loan.end_date.isoformat(),
    }


# The KPI « Matériel prêté »


def test_the_kpi_counts_the_loans_out_and_names_the_first_due_back(board_client, board):
    """
    Given three loans out, one of them late, and two to prepare
    When a member opens the dashboard
    Then three loans are out, two to prepare, and the late one comes back first
    """
    loans = board_client.get(OVERVIEW).json()["loans"]

    assert loans == {
        "out_count": 3,
        "to_prepare_count": 2,
        "next_return": brief(board["overdue"], "overdue"),
    }


# The block « Matériel : sorties et retours »


def test_the_block_lists_the_checkouts_and_returns_of_the_fortnight(board_client, board):
    """
    Given loans out and confirmed around today, one leaving on the fourteenth
    day and others beyond, a committee loan, a loan returned and one cancelled
    When a member opens the dashboard
    Then the late return comes first, then each checkout and return of the
    fortnight by its day; a committee loan has neither
    """
    movements = board_client.get(OVERVIEW).json()["loan_movements"]

    assert [(item["kind"], item["loan"]["display_name"], item["day"]) for item in movements] == [
        ("return", "Tennis", ahead(-2).isoformat()),
        ("checkout", "Pétanque", ahead(-1).isoformat()),
        ("return", "École du village", ahead(1).isoformat()),
        ("checkout", "M. Petit", ahead(2).isoformat()),
        ("checkout", "Club de football", ahead(13).isoformat()),
    ]
    school = movements[2]["loan"]
    assert (school["state"], [line["quantity"] for line in school["lines"]]) == ("out", [2])


def test_the_block_shows_the_first_eight_movements(board_client, marquees):
    """
    Given nine loans leaving within the fortnight
    When a member opens the dashboard
    Then the block shows the first eight: the Prêts page holds them all
    """
    for days in range(9):
        lend(marquees, 1, ahead(days), ahead(days), borrower_name=f"Club {days}")

    movements = board_client.get(OVERVIEW).json()["loan_movements"]

    assert [item["loan"]["display_name"] for item in movements] == [
        f"Club {days}" for days in range(8)
    ]


# The bell


def test_the_bell_lists_the_late_loans_then_those_to_prepare(board_client, board):
    """
    Given a loan late, two to prepare, and a document to review
    When a member opens the dashboard
    Then the bell counts four items, and lists the late loan, then those to
    prepare, the first to leave first
    """
    DocumentFactory()

    pending = board_client.get(OVERVIEW).json()["pending"]

    assert pending["total"] == 4
    assert pending["loans"] == {
        "overdue": 1,
        "to_prepare": 2,
        "items": [
            brief(board["overdue"], "overdue"),
            brief(board["late_checkout"], "to_prepare"),
            brief(board["to_prepare"], "to_prepare"),
        ],
    }


def test_the_bell_lists_ten_loans_at_most(board_client, marquees):
    """
    Given eleven loans to prepare
    When a member opens the dashboard
    Then the bell counts them all, and lists the first ten
    """
    for days in range(11):
        lend(marquees, 1, ahead(days % 7), ahead(7), borrower_name=f"Club {days}")

    loans = board_client.get(OVERVIEW).json()["pending"]["loans"]

    assert (loans["to_prepare"], len(loans["items"])) == (11, 10)


# An event's page


def event_dashboard_url(event_id):
    return f"/api/board/events/{event_id}/dashboard"


def test_an_events_dashboard_shows_the_equipment_it_keeps(board_client, marquees):
    """
    Given Halloween, which keeps two marquees and twelve benches
    When a member opens its page
    Then its equipment tab counts two lines, and its block shows them
    """
    event = EventFactory(title="Halloween des enfants")
    reservation = CommitteeLoanFactory(event=event, start_date=ahead(29), end_date=ahead(31))
    benches = EquipmentFactory(name="Bancs pliants", total_quantity=40)
    lines = [
        LoanLineFactory(loan=reservation, equipment=marquees, quantity=2),
        LoanLineFactory(loan=reservation, equipment=benches, quantity=12),
    ]

    dashboard = board_client.get(event_dashboard_url(event.id)).json()

    assert dashboard["equipment_count"] == 2
    assert dashboard["committee_loan"] == {
        **brief(reservation, "committee"),
        "display_name": "Halloween des enfants",
        "lines": [
            {
                "id": line.id,
                "equipment": {
                    "id": line.equipment.id,
                    "name": line.equipment.name,
                    "unit_value": "250.00",
                },
                "quantity": line.quantity,
                "damaged_quantity": 0,
                "missing_quantity": 0,
            }
            for line in sorted(lines, key=lambda line: line.equipment.name)
        ],
    }


def test_a_cancelled_reservation_keeps_no_equipment(board_client):
    """
    Given an event whose reservation was cancelled
    When a member opens its page
    Then it keeps no equipment
    """
    event = EventFactory()
    LoanLineFactory(loan=CommitteeLoanFactory(event=event, status=LoanStatus.CANCELLED))

    dashboard = board_client.get(event_dashboard_url(event.id)).json()

    assert (dashboard["equipment_count"], dashboard["committee_loan"]) == (0, None)


def test_an_event_keeps_none_of_another_events_equipment(board_client):
    event = EventFactory()
    LoanLineFactory(loan=CommitteeLoanFactory(event=EventFactory()))
    LoanFactory()

    dashboard = board_client.get(event_dashboard_url(event.id)).json()

    assert (dashboard["equipment_count"], dashboard["committee_loan"]) == (0, None)
