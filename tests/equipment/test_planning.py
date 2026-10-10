import datetime as dt

import pytest
from django.utils import timezone

from equipment.models import LoanStatus
from equipment.services.loans import loan_planning
from tests.equipment.factories import CommitteeLoanFactory, EquipmentFactory, lend

pytestmark = pytest.mark.django_db

PLANNING = "/api/board/loans/planning"

# Thursday 1 October 2026: the window runs from Monday 21 September to Sunday 22 November.
TODAY = dt.date(2026, 10, 1)


def test_the_planning_runs_nine_weeks_from_the_monday_before():
    """
    Given Thursday 1 October
    When the planning is read
    Then its window runs from Monday 21 September, for nine weeks
    """
    planning = loan_planning(today=TODAY)

    assert (planning.start, planning.end) == (dt.date(2026, 9, 21), dt.date(2026, 11, 22))


def test_the_planning_draws_the_loans_that_overlap_its_window():
    """
    Given loans across its edges, within it, beyond it, returned or cancelled
    When the planning is read on 1 October
    Then it holds those that overlap its window, returned ones and the
    committee's included, the cancelled left out, the first to start first
    """
    marquees = EquipmentFactory()
    day = dt.date
    before = lend(marquees, 1, day(2026, 9, 10), day(2026, 9, 20))
    across_start = lend(
        marquees,
        1,
        day(2026, 9, 19),
        day(2026, 9, 22),
        status=LoanStatus.RETURNED,
        returned_at=timezone.now(),
    )
    committee = CommitteeLoanFactory(start_date=day(2026, 10, 30), end_date=day(2026, 11, 1))
    across_end = lend(marquees, 1, day(2026, 11, 22), day(2026, 11, 24))
    lend(marquees, 1, day(2026, 11, 23), day(2026, 11, 25))
    lend(marquees, 1, day(2026, 10, 5), day(2026, 10, 6), status=LoanStatus.CANCELLED)

    planning = loan_planning(today=TODAY)

    assert planning.loans == [across_start, committee, across_end]
    assert [loan.state for loan in planning.loans] == ["returned", "committee", "confirmed"]
    assert before not in planning.loans


def test_a_member_reads_the_planning(board_client, django_assert_max_num_queries):
    """
    Given five loans this week, one of them the committee's
    When a member reads the planning
    Then each loan comes with its state, in a fixed number of queries
    """
    today = timezone.localdate()
    for _ in range(4):
        lend(EquipmentFactory(), 1, today, today)
    CommitteeLoanFactory(start_date=today, end_date=today)

    # Authentication (2), the loans with their events.
    with django_assert_max_num_queries(3):
        response = board_client.get(PLANNING)

    assert response.status_code == 200
    body = response.json()
    assert len(body["loans"]) == 5
    assert {loan["state"] for loan in body["loans"]} == {"to_prepare", "committee"}
    assert body["start"] == (today - dt.timedelta(days=today.weekday() + 7)).isoformat()
