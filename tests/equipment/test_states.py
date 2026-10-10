import datetime as dt

import pytest

from equipment.models import LoanState, LoanStatus
from equipment.services.states import loan_state
from tests.equipment.factories import CommitteeLoanFactory, LoanFactory

TODAY = dt.date(2026, 10, 1)


def days(number):
    return TODAY + dt.timedelta(days=number)


@pytest.mark.parametrize(
    ("status", "start", "end", "state"),
    [
        (LoanStatus.CONFIRMED, days(7), days(9), LoanState.TO_PREPARE),
        (LoanStatus.CONFIRMED, days(-2), days(1), LoanState.TO_PREPARE),
        (LoanStatus.CONFIRMED, days(8), days(9), LoanState.CONFIRMED),
        (LoanStatus.OUT, days(-2), days(0), LoanState.OUT),
        (LoanStatus.OUT, days(-3), days(-1), LoanState.OVERDUE),
        (LoanStatus.RETURNED, days(-3), days(-1), LoanState.RETURNED),
        (LoanStatus.CANCELLED, days(2), days(3), LoanState.CANCELLED),
    ],
)
def test_a_loan_stands_where_its_status_and_dates_put_it(status, start, end, state):
    """
    Given a loan to someone, with its status and its days, on 1 October
    When its state is worked out
    Then a confirmed loan is to prepare within a week of its start, or once
    its start has passed without a checkout, and a loan out is overdue the day
    after its end
    """
    loan = LoanFactory.build(status=status, start_date=start, end_date=end)

    assert loan_state(loan, TODAY) == state


@pytest.mark.parametrize(
    ("status", "state"),
    [
        (LoanStatus.CONFIRMED, LoanState.COMMITTEE),
        (LoanStatus.CANCELLED, LoanState.CANCELLED),
    ],
)
def test_a_committee_loan_is_never_to_prepare(status, state):
    """
    Given the equipment the committee keeps for its event in three days
    When the state of its reservation is worked out
    Then it is « Usage comité », with neither checkout nor return, until it is
    cancelled
    """
    loan = CommitteeLoanFactory.build(status=status, start_date=days(3), end_date=days(4))

    assert loan_state(loan, TODAY) == state
