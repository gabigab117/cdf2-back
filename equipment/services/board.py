"""What the board reads of the loans away from the Prêts page: the dashboard's
KPI « Matériel prêté » and block « Matériel : sorties et retours », the loans
the bell lists, and the equipment an event keeps.
"""

import datetime as dt
from dataclasses import dataclass

from django.db.models import Case, F, Q, When

from equipment.models import Loan, LoanBorrowerType, LoanState, LoanStatus
from equipment.services.loans import loans
from equipment.services.states import in_board_order, with_states
from events.models import Event

# The block « Matériel : sorties et retours »: the next fortnight, today included.
MOVEMENT_DAYS = 14

# Its rows at most: the Prêts page holds them all.
MOVEMENTS_COUNT = 8

# The loans the « À traiter » panel lists: a bounded aggregate (A7), whose
# counts lead to them all.
PENDING_LOANS_COUNT = 10


@dataclass(frozen=True)
class LoanMovement:
    """The next step of a loan within the fortnight: the checkout of a loan
    confirmed, or the return of a loan out.
    """

    # "checkout" or "return".
    kind: str
    day: dt.date
    loan: Loan


def next_return(today: dt.date) -> Loan | None:
    """The loan out due back first, a late one before all: none when nothing is out."""
    out = with_states(Loan.objects.select_related("event"), today).filter(status=LoanStatus.OUT)
    return out.order_by("end_date", "pk").first()


def loan_movements(today: dt.date) -> list[LoanMovement]:
    """The checkouts and returns of the fortnight, the earliest first: a late
    return, or a checkout whose day has passed, before all. A committee loan
    has neither.
    """
    horizon = today + dt.timedelta(days=MOVEMENT_DAYS - 1)
    moving = (
        with_states(loans(), today)
        .filter(
            Q(status=LoanStatus.OUT, end_date__lte=horizon)
            | (
                Q(status=LoanStatus.CONFIRMED, start_date__lte=horizon)
                & ~Q(borrower_type=LoanBorrowerType.COMMITTEE)
            )
        )
        .annotate(
            day=Case(When(status=LoanStatus.OUT, then=F("end_date")), default=F("start_date"))
        )
        .order_by("day", "pk")
    )
    return [
        LoanMovement("return" if loan.status == LoanStatus.OUT else "checkout", loan.day, loan)
        for loan in moving[:MOVEMENTS_COUNT]
    ]


def pending_loans(today: dt.date) -> list[Loan]:
    """The loans that call for the board, as the list orders them: the late
    ones, then those to prepare. The first ten.
    """
    calling = in_board_order(Loan.objects.select_related("event"), today).filter(
        state__in=[LoanState.OVERDUE, LoanState.TO_PREPARE]
    )
    return list(calling[:PENDING_LOANS_COUNT])


def event_reservation(event: Event, today: dt.date) -> Loan | None:
    """The equipment an event keeps: its reservation, unless cancelled."""
    kept = loans().filter(event=event).exclude(status=LoanStatus.CANCELLED)
    return with_states(kept, today).first()
