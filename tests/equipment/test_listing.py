import datetime as dt

import pytest
from django.utils import timezone

from equipment.models import Loan, LoanStatus
from equipment.services.loans import listed_loans
from equipment.services.states import loan_state
from tests.equipment.factories import CommitteeLoanFactory, EquipmentFactory, LoanLineFactory, lend

pytestmark = pytest.mark.django_db

LOANS = "/api/board/loans"
TODAY = dt.date(2026, 10, 1)


def ahead(days, today=TODAY):
    return today + dt.timedelta(days=days)


def returned(**fields):
    return {"status": LoanStatus.RETURNED, "returned_at": timezone.now(), **fields}


@pytest.fixture
def board(db):
    """A loan of each state, on 1 October, created in no particular order."""
    marquees = EquipmentFactory()
    return {
        "returned_last": lend(
            marquees, 1, ahead(-5), ahead(-3), **returned(borrower_name="Mairie")
        ),
        "confirmed": lend(marquees, 1, ahead(20), ahead(21), borrower_name="Club de football"),
        "committee_past": CommitteeLoanFactory(start_date=ahead(-30), end_date=ahead(-28)),
        "to_prepare": lend(marquees, 1, ahead(5), ahead(6), borrower_name="M. Petit"),
        "out": lend(marquees, 1, ahead(-1), ahead(1), status=LoanStatus.OUT, borrower_name="École"),
        "returned_first": lend(
            marquees, 1, ahead(-12), ahead(-10), **returned(borrower_name="Parents")
        ),
        "committee": CommitteeLoanFactory(start_date=ahead(29), end_date=ahead(31)),
        "overdue": lend(
            marquees, 1, ahead(-6), ahead(-2), status=LoanStatus.OUT, borrower_name="Tennis"
        ),
        "cancelled": lend(
            marquees, 1, ahead(9), ahead(10), status=LoanStatus.CANCELLED, borrower_name="Judo"
        ),
        "to_prepare_late": lend(marquees, 1, ahead(-1), ahead(2), borrower_name="Pétanque"),
    }


def test_the_database_works_out_each_state_as_the_service_does(board):
    """
    Given a loan of each state on 1 October, and loans at their bounds: one out
    due back today, one leaving in seven days, one in eight
    When the list works out their states
    Then each is the state loan_state() gives it
    """
    marquees = EquipmentFactory()
    lend(marquees, 1, ahead(-2), ahead(0), status=LoanStatus.OUT, borrower_name="Due today")
    lend(marquees, 1, ahead(7), ahead(8), borrower_name="In seven days")
    lend(marquees, 1, ahead(8), ahead(9), borrower_name="In eight days")

    states = {loan.borrower_name: loan.state for loan in listed_loans(today=TODAY)}

    for loan in Loan.objects.all():
        assert states[loan.borrower_name] == loan_state(loan, TODAY), loan.borrower_name
    assert (states["Due today"], states["In seven days"], states["In eight days"]) == (
        "out",
        "to_prepare",
        "confirmed",
    )


def test_the_list_calls_for_the_board_first_then_what_is_over(board):
    """
    Given a loan of each state, on 1 October
    When the list orders them
    Then come the late, the out, those to prepare, the confirmed and the
    committee's to come, each the first to start first; then those over,
    returned, cancelled or the committee's past, the latest first
    """
    order = [loan.pk for loan in listed_loans(today=TODAY)]

    assert order == [
        board[key].pk
        for key in (
            "overdue",
            "out",
            "to_prepare_late",
            "to_prepare",
            "confirmed",
            "committee",
            "cancelled",
            "returned_last",
            "returned_first",
            "committee_past",
        )
    ]


def test_a_member_lists_the_loans_of_a_state(board_client):
    """
    Given a loan out, overdue, and one to prepare, today
    When a member lists those overdue
    Then the overdue one alone comes, with its lines and how they came back
    """
    today = timezone.localdate()
    marquees = EquipmentFactory(name="Barnums 3 × 3 m")
    late = lend(
        marquees, 2, ahead(-6, today), ahead(-2, today), status=LoanStatus.OUT, number="P-2026-018"
    )
    lend(marquees, 1, ahead(3, today), ahead(4, today))

    response = board_client.get(LOANS, {"state": "overdue"})

    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "id": late.id,
                "number": "P-2026-018",
                "display_name": "Club de football",
                "purpose": "Tournoi jeunes",
                "borrower_type": "association",
                "state": "overdue",
                "start_date": ahead(-6, today).isoformat(),
                "end_date": ahead(-2, today).isoformat(),
                "lines": [
                    {
                        "id": late.lines.get().id,
                        "equipment": {
                            "id": marquees.id,
                            "name": "Barnums 3 × 3 m",
                            "unit_value": "250.00",
                        },
                        "quantity": 2,
                        "damaged_quantity": 0,
                        "missing_quantity": 0,
                    }
                ],
            }
        ],
        "count": 1,
    }


def test_a_member_counts_the_loans_of_each_state(board_client):
    """
    Given two loans to prepare, one out and one cancelled, today
    When a member counts the loans
    Then each state has its count, and the total holds them all
    """
    today = timezone.localdate()
    marquees = EquipmentFactory()
    lend(marquees, 1, ahead(1, today), ahead(2, today))
    lend(marquees, 1, ahead(3, today), ahead(4, today))
    lend(marquees, 1, ahead(-1, today), ahead(1, today), status=LoanStatus.OUT)
    lend(marquees, 1, ahead(5, today), ahead(6, today), status=LoanStatus.CANCELLED)

    response = board_client.get(f"{LOANS}/counts")

    assert response.status_code == 200
    assert response.json() == {
        "total": 4,
        "to_prepare": 2,
        "confirmed": 0,
        "out": 1,
        "overdue": 0,
        "committee": 0,
        "returned": 0,
        "cancelled": 1,
    }


def test_listing_the_loans_takes_a_fixed_number_of_queries(
    board_client, django_assert_max_num_queries
):
    """
    Given five loans of two lines each, the committee's among them
    When a member lists them
    Then their events and lines come in a fixed number of queries
    """
    for _ in range(4):
        LoanLineFactory.create_batch(2, loan=lend(EquipmentFactory(), 1, ahead(3), ahead(4)))
    LoanLineFactory.create_batch(2, loan=CommitteeLoanFactory())

    # Authentication (2), the count, the page with the events, the lines with their equipment.
    with django_assert_max_num_queries(5):
        board_client.get(LOANS)
