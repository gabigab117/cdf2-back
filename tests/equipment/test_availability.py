import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from equipment.models import LoanState, LoanStatus
from equipment.services.availability import (
    availability,
    availability_report,
    check_period,
    shortages,
)
from tests.equipment.factories import EquipmentFactory, lend
from tests.equipment.mockup import TODAY, build_mockup
from tests.events.factories import EventFactory

pytestmark = pytest.mark.django_db


def day(month, number):
    return dt.date(2026, month, number)


@pytest.fixture
def mockup():
    return build_mockup()


# The references of the mockup (A15)


def test_marquees_are_counted_at_their_daily_peak_not_their_sum(mockup):
    """
    Given the marquees of the mockup, kept four times from 28 September to 14 December
    When their availability over that period is computed, on 1 October
    Then the loans take 9 pieces in all, but 3 at most on a single day
    """
    [item] = availability([mockup.equipment["b33"]], day(9, 28), day(12, 14), today=TODAY)

    assert sum(conflict.quantity for conflict in item.conflicts) == 9
    assert item.taken == 3
    assert [conflict.loan for conflict in item.conflicts] == [
        mockup.loans[key] for key in ("cross", "tournoi", "halloween", "noel")
    ]


def test_tables_leave_three_free_from_mid_october_to_mid_november(mockup):
    """
    Given the 24 tables of the mockup, one of them under repair
    When their availability from 16 October to 15 November is computed
    Then the 20 tables of the loto are the peak, and 3 remain free
    """
    [item] = availability([mockup.equipment["tables"]], day(10, 16), day(11, 15), today=TODAY)

    assert (item.taken, item.free) == (20, 3)


def test_each_loan_in_conflict_carries_its_state(mockup):
    """
    Given the loans of the mockup, on 1 October
    When the availability of all the equipment until mid-December is computed
    Then each loan in conflict tells where it stands: out, to prepare,
    confirmed, or kept for an event of the committee
    """
    items = availability(mockup.equipment.values(), day(9, 28), day(12, 14), today=TODAY)

    states = {
        conflict.loan.pk: conflict.loan.state for item in items for conflict in item.conflicts
    }
    loans = mockup.loans
    assert states == {
        loans["cross"].pk: LoanState.OUT,
        loans["anniversaire"].pk: LoanState.TO_PREPARE,
        loans["tournoi"].pk: LoanState.CONFIRMED,
        loans["pomme"].pk: LoanState.CONFIRMED,
        loans["halloween"].pk: LoanState.COMMITTEE,
        loans["loto"].pk: LoanState.COMMITTEE,
        loans["noel"].pk: LoanState.COMMITTEE,
    }


# Days counted


def test_a_return_and_a_checkout_on_the_same_day_are_in_conflict():
    """
    Given a marquee lent until 18 October
    When the marquees are counted from 18 to 19 October
    Then that loan still takes its piece: both its days count
    """
    marquee = EquipmentFactory(total_quantity=1)
    lend(marquee, 1, day(10, 16), day(10, 18))

    [item] = availability([marquee], day(10, 18), day(10, 19), today=TODAY)

    assert (item.taken, item.free) == (1, 0)


def test_a_loan_ending_the_day_before_another_never_holds_the_same_piece():
    """
    Given two marquees, one lent until 18 October, then one from 19 October
    When the marquees are counted from 17 to 20 October
    Then both loans are in conflict, but never on the same day: the peak is one
    """
    marquees = EquipmentFactory(total_quantity=2)
    lend(marquees, 1, day(10, 16), day(10, 18))
    lend(marquees, 1, day(10, 19), day(10, 21))

    [item] = availability([marquees], day(10, 17), day(10, 20), today=TODAY)

    assert (item.taken, item.free, len(item.conflicts)) == (1, 1, 2)


# What counts


def test_the_loan_being_edited_does_not_stand_in_its_own_way():
    """
    Given two marquees, both taken by a loan
    When the marquees are counted for that loan being edited
    Then its own pieces are left out: both are free for it
    """
    marquees = EquipmentFactory(total_quantity=2)
    edited = lend(marquees, 2, day(10, 16), day(10, 18))

    [item] = availability([marquees], day(10, 16), day(10, 18), exclude_loan=edited.pk, today=TODAY)

    assert (item.taken, item.free, item.conflicts) == (0, 2, [])


def test_pieces_under_repair_are_never_free_and_free_never_falls_below_zero():
    """
    Given 4 marquees, 3 of them under repair, and a loan that took 2 before
    When the marquees are counted over that loan
    Then none is free, rather than less than none
    """
    marquees = EquipmentFactory(total_quantity=4, repair_quantity=3)
    lend(marquees, 2, day(10, 16), day(10, 18))

    [item] = availability([marquees], day(10, 16), day(10, 18), today=TODAY)

    assert (item.taken, item.free) == (2, 0)


def test_returned_and_cancelled_loans_free_their_pieces_but_a_committee_holds_its_own():
    """
    Given marquees returned by one loan, cancelled by another, and kept by the
    committee for one of its events, over the same days
    When the marquees are counted over those days
    Then only the committee's pieces are taken
    """
    marquees = EquipmentFactory(total_quantity=5)
    lend(
        marquees,
        1,
        day(10, 16),
        day(10, 18),
        status=LoanStatus.RETURNED,
        returned_at=timezone.now(),
    )
    lend(marquees, 1, day(10, 16), day(10, 18), status=LoanStatus.CANCELLED)
    kept = lend(marquees, 2, day(10, 16), day(10, 18), event=EventFactory())

    [item] = availability([marquees], day(10, 16), day(10, 18), today=TODAY)

    assert item.taken == 2
    assert [conflict.loan for conflict in item.conflicts] == [kept]


# Effective dates (A15)


def test_an_overdue_loan_holds_its_pieces_until_today():
    """
    Given a marquee out since 28 September, due back on 30 September, on 1 October
    When the marquees are counted for today, then for tomorrow
    Then the overdue loan takes it today, its effective end, and not tomorrow
    """
    marquee = EquipmentFactory(total_quantity=1)
    lend(marquee, 1, day(9, 28), day(9, 30), status=LoanStatus.OUT)

    [today] = availability([marquee], TODAY, TODAY, today=TODAY)
    [tomorrow] = availability([marquee], day(10, 2), day(10, 2), today=TODAY)

    assert (today.taken, today.conflicts[0].end) == (1, TODAY)
    assert today.conflicts[0].loan.state == LoanState.OVERDUE
    assert tomorrow.taken == 0


def test_a_loan_handed_over_before_its_start_holds_its_pieces_from_today():
    """
    Given a marquee handed over on 1 October, for a loan from 3 to 5 October
    When the marquees are counted for today
    Then the loan already takes it: its effective start is today
    """
    marquee = EquipmentFactory(total_quantity=1)
    lend(marquee, 1, day(10, 3), day(10, 5), status=LoanStatus.OUT)

    [item] = availability([marquee], TODAY, TODAY, today=TODAY)

    assert (item.taken, item.conflicts[0].start) == (1, TODAY)


# The period


@pytest.mark.parametrize(
    ("start", "end", "message"),
    [
        (day(10, 18), day(10, 17), "La date de retour est avant la date de sortie."),
        (day(10, 1), day(11, 1), "Un prêt dure au plus 31 jours."),
    ],
)
def test_a_period_no_loan_could_cover_is_refused(start, end, message):
    """
    Given a period that ends before it starts, or lasts 32 days
    When it is checked
    Then it is refused: no loan could cover it
    """
    with pytest.raises(ValidationError) as error:
        check_period(start, end)

    assert error.value.messages == [message]


def test_the_report_covers_a_period_of_a_month():
    """
    Given a marquee
    When the report of what is free over 31 days, both counted, is asked
    Then it covers that period, for every equipment given
    """
    marquee = EquipmentFactory()

    report = availability_report([marquee], day(10, 1), day(10, 31), None)

    assert (report.start, report.end) == (day(10, 1), day(10, 31))
    assert [item.equipment for item in report.items] == [marquee]


# Shortages (A17)


def test_no_equipment_is_short_while_the_loans_fit(mockup):
    """
    Given the equipment and the loans of the mockup
    When the shortages from 1 October are looked for
    Then there is none
    """
    assert shortages(mockup.equipment.values(), today=TODAY) == []


def test_a_piece_more_under_repair_leaves_a_loan_to_come_short(mockup):
    """
    Given the marquees of the mockup: 4, one under repair, 3 kept for Christmas
    When a second one goes under repair, before it is saved
    Then they are short from 11 December: the market takes 3, 2 are offered
    """
    marquees = mockup.equipment["b33"]
    marquees.repair_quantity = 2

    [shortage] = shortages([marquees], today=TODAY)

    assert (shortage.equipment, shortage.day) == (marquees, day(12, 11))
    assert (shortage.offered, shortage.taken) == (2, 3)
    assert shortage.loans == [mockup.loans["noel"]]


def test_a_shortage_names_every_loan_short_from_the_first_day(mockup):
    """
    Given the marquees of the mockup, three of them under repair
    When the shortages from 1 October are looked for
    Then every loan of them to come is short, from today, by the most taken
    """
    marquees = mockup.equipment["b33"]
    marquees.repair_quantity = 3

    [shortage] = shortages([marquees], today=TODAY)

    assert (shortage.day, shortage.offered, shortage.taken) == (TODAY, 1, 3)
    assert shortage.loans == [
        mockup.loans[key] for key in ("cross", "tournoi", "halloween", "noel")
    ]


def test_a_loan_ended_before_today_is_never_short():
    """
    Given a marquee, and a confirmed loan of two that ended last week
    When the shortages are looked for today
    Then none is found: the days past are not looked at
    """
    marquee = EquipmentFactory(total_quantity=1)
    lend(marquee, 2, day(9, 20), day(9, 22))

    assert shortages([marquee], today=TODAY) == []
