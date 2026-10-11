import datetime as dt

import pytest
from django.utils import timezone

from core.text import ERASED_NAME
from equipment.models import LoanBorrowerType, LoanStatus
from equipment.services.purge import LoanPurge, purge_loans
from tests.equipment.factories import CommitteeLoanFactory, LoanFactory

pytestmark = pytest.mark.django_db

# Three months and a year before it are days of their own: no month end moves
# the boundaries.
TODAY = dt.date(2027, 6, 15)
PHONE = "01 23 45 67 89"


def at(day, time=dt.time(18)):
    """An instant of a day, in Paris."""
    return timezone.make_aware(dt.datetime.combine(day, time))


def returned(day, time=dt.time(18), **fields):
    """A loan, to an association unless told otherwise, returned on a day."""
    return LoanFactory(
        status=LoanStatus.RETURNED,
        returned_at=at(day, time),
        start_date=day - dt.timedelta(days=2),
        end_date=day,
        phone=PHONE,
        **fields,
    )


def cancelled(end, **fields):
    """A loan cancelled before its checkout, its return planned on a day."""
    return LoanFactory(
        status=LoanStatus.CANCELLED,
        start_date=end - dt.timedelta(days=2),
        end_date=end,
        phone=PHONE,
        **fields,
    )


def to_a_person(**fields):
    return {
        "borrower_type": LoanBorrowerType.INDIVIDUAL,
        "borrower_name": "M. Petit",
        "purpose": "Anniversaire",
        "notes": "Rappeler la veille.",
        **fields,
    }


def reloaded(*loans):
    for loan in loans:
        loan.refresh_from_db()
    return loans


def test_a_borrowers_phone_is_erased_three_months_after_the_return():
    """
    Given a loan returned on 15 March, and another returned on 16 March
    When the purge runs on 15 June
    Then the first loses its borrower's phone, three months after its return
    And the second keeps it until the next night
    """
    over = returned(dt.date(2027, 3, 15))
    kept = returned(dt.date(2027, 3, 16))

    purge = purge_loans(TODAY)

    reloaded(over, kept)
    assert (over.phone, kept.phone) == ("", PHONE)
    assert purge == LoanPurge(phones=1, names=0)


def test_a_return_is_dated_in_paris():
    """
    Given a loan returned at half past midnight on 16 March in Paris, still 15
    March in UTC
    When the purge runs on 15 June
    Then the loan keeps its borrower's phone: it came back on 16 March
    """
    loan = returned(dt.date(2027, 3, 16), time=dt.time(0, 30))

    purge_loans(TODAY)

    reloaded(loan)
    assert loan.phone == PHONE


def test_at_a_month_end_the_period_ends_the_next_day():
    """
    Given a loan returned on 30 November
    When the purge runs on 28 February, three months back being 28 November
    Then the loan keeps its borrower's phone
    And the purge of 1 March erases it
    """
    loan = returned(dt.date(2026, 11, 30))

    purge_loans(dt.date(2027, 2, 28))
    reloaded(loan)
    assert loan.phone == PHONE

    purge_loans(dt.date(2027, 3, 1))
    reloaded(loan)
    assert loan.phone == ""


def test_a_cancelled_loan_counts_from_its_planned_return():
    """
    Given loans cancelled with their return planned on 15 and 16 March, and loans
    to a person cancelled with their return planned on 15 and 16 June last year
    When the purge runs on 15 June
    Then the phone of the first goes, three months after its planned return
    And the person's name and notes of the third go, a year after it
    And the others keep theirs until the next night
    """
    phone_over = cancelled(dt.date(2027, 3, 15))
    phone_kept = cancelled(dt.date(2027, 3, 16))
    name_over = cancelled(dt.date(2026, 6, 15), **to_a_person())
    name_kept = cancelled(dt.date(2026, 6, 16), **to_a_person())

    purge = purge_loans(TODAY)

    reloaded(phone_over, phone_kept, name_over, name_kept)
    assert (phone_over.phone, phone_kept.phone) == ("", PHONE)
    assert (name_over.borrower_name, name_over.notes) == (ERASED_NAME, "")
    assert (name_kept.borrower_name, name_kept.notes) == ("M. Petit", "Rappeler la veille.")
    assert purge == LoanPurge(phones=3, names=1)


def test_a_loan_the_board_has_not_closed_keeps_its_data():
    """
    Given a loan to a person still confirmed, and another still out, both due
    back a year ago
    When the purge runs
    Then both keep the person's name and phone: neither came back nor was
    cancelled
    """
    due = {"start_date": dt.date(2026, 6, 1), "end_date": dt.date(2026, 6, 3), "phone": PHONE}
    confirmed = LoanFactory(**due, **to_a_person())
    out = LoanFactory(status=LoanStatus.OUT, **due, **to_a_person())

    purge = purge_loans(TODAY)

    reloaded(confirmed, out)
    assert {(loan.borrower_name, loan.phone) for loan in (confirmed, out)} == {("M. Petit", PHONE)}
    assert purge == LoanPurge(phones=0, names=0)


def test_a_persons_name_and_notes_are_erased_a_year_after_the_return():
    """
    Given a loan to a person returned on 15 June last year, and another
    returned on 16 June
    When the purge runs on 15 June
    Then the borrower of the first is « Nom effacé » and its notes are erased,
    its purpose kept
    And the second keeps its borrower and its notes until the next night
    And both lost their phone long ago
    """
    over = returned(dt.date(2026, 6, 15), **to_a_person())
    kept = returned(dt.date(2026, 6, 16), **to_a_person())

    purge = purge_loans(TODAY)

    reloaded(over, kept)
    assert (over.borrower_name, over.notes, over.purpose) == (ERASED_NAME, "", "Anniversaire")
    assert (kept.borrower_name, kept.notes) == ("M. Petit", "Rappeler la veille.")
    assert (over.phone, kept.phone) == ("", "")
    assert purge == LoanPurge(phones=2, names=1)


def test_an_association_and_the_committee_keep_their_name_and_notes():
    """
    Given a loan to an association and the committee's reservation of equipment,
    both with notes, closed two years ago
    When the purge runs
    Then both keep their name and their notes: neither is a person
    And the association's phone alone is erased
    """
    association = returned(dt.date(2025, 6, 1), notes="Clés au local.")
    committee = CommitteeLoanFactory(
        status=LoanStatus.CANCELLED,
        start_date=dt.date(2025, 6, 1),
        end_date=dt.date(2025, 6, 3),
        notes="Pour la kermesse.",
    )

    purge = purge_loans(TODAY)

    reloaded(association, committee)
    assert (association.borrower_name, association.notes, association.phone) == (
        "Club de football",
        "Clés au local.",
        "",
    )
    assert committee.notes == "Pour la kermesse."
    assert purge == LoanPurge(phones=1, names=0)


def test_the_purge_counts_only_what_it_erases():
    """
    Given a loan to a person returned two years ago
    When the purge runs, then again the next night
    Then the first counts its phone and its name, the second nothing
    And a note the board writes on it afterwards goes the night after
    """
    loan = returned(dt.date(2025, 6, 15), **to_a_person())

    assert purge_loans(TODAY) == LoanPurge(phones=1, names=1)
    assert purge_loans(TODAY) == LoanPurge(phones=0, names=0)

    loan.refresh_from_db()
    loan.notes = "Caution rendue."
    loan.save(update_fields=["notes"])

    assert purge_loans(TODAY) == LoanPurge(phones=0, names=1)
    reloaded(loan)
    assert (loan.borrower_name, loan.notes) == (ERASED_NAME, "")
