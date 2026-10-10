"""Where a loan stands today (A14): its recorded status, read with its dates.

« À préparer » is a confirmed loan that leaves within a week, or whose start
has passed without a checkout; « En retard », a loan out past its end. A
committee loan has neither checkout nor return: it stays « Usage comité ».
"""

import datetime as dt

from django.db.models import Case, CharField, F, QuerySet, Value, When

from equipment.models import Loan, LoanBorrowerType, LoanState, LoanStatus

# How far ahead a loan is to be prepared: the week before it leaves.
PREPARATION_DAYS = 7


def loan_state(loan: Loan, today: dt.date) -> LoanState:
    """The state of a loan on a given day."""
    if loan.status == LoanStatus.CANCELLED:
        return LoanState.CANCELLED
    if loan.status == LoanStatus.RETURNED:
        return LoanState.RETURNED
    if loan.borrower_type == LoanBorrowerType.COMMITTEE:
        return LoanState.COMMITTEE
    if loan.status == LoanStatus.OUT:
        return LoanState.OVERDUE if loan.end_date < today else LoanState.OUT
    if loan.start_date <= today + dt.timedelta(days=PREPARATION_DAYS):
        return LoanState.TO_PREPARE
    return LoanState.CONFIRMED


def with_states(loans: QuerySet[Loan], today: dt.date) -> QuerySet[Loan]:
    """Loans with their state of a day, worked out by the database as
    loan_state() works it out: a list filters and orders them by it.
    """
    soon = today + dt.timedelta(days=PREPARATION_DAYS)
    return loans.annotate(
        state=Case(
            When(status=LoanStatus.CANCELLED, then=Value(LoanState.CANCELLED)),
            When(status=LoanStatus.RETURNED, then=Value(LoanState.RETURNED)),
            When(borrower_type=LoanBorrowerType.COMMITTEE, then=Value(LoanState.COMMITTEE)),
            When(status=LoanStatus.OUT, end_date__lt=today, then=Value(LoanState.OVERDUE)),
            When(status=LoanStatus.OUT, then=Value(LoanState.OUT)),
            When(start_date__lte=soon, then=Value(LoanState.TO_PREPARE)),
            default=Value(LoanState.CONFIRMED),
            output_field=CharField(),
        )
    )


# The order of the list: what calls for the board first, then what is over.
_GROUPS = [LoanState.OVERDUE, LoanState.OUT, LoanState.TO_PREPARE, LoanState.CONFIRMED]
_OVER = len(_GROUPS) + 1


def in_board_order(loans: QuerySet[Loan], today: dt.date) -> QuerySet[Loan]:
    """Loans with their state, in the order of the list: late, out, to prepare,
    confirmed, then the committee's to come, each the first to start first;
    then the returned, the cancelled and the committee's past, the latest first.
    """
    group = Case(
        *(When(state=state, then=Value(index)) for index, state in enumerate(_GROUPS)),
        When(state=LoanState.COMMITTEE, end_date__gte=today, then=Value(len(_GROUPS))),
        default=Value(_OVER),
    )
    return (
        with_states(loans, today)
        .annotate(group=group)
        .annotate(
            upcoming_start=Case(When(group__lt=_OVER, then=F("start_date"))),
            past_start=Case(When(group=_OVER, then=F("start_date"))),
        )
        .order_by("group", "upcoming_start", "-past_start", "-pk")
    )
