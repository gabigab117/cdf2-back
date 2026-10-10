"""Where a loan stands today (A14): its recorded status, read with its dates.

« À préparer » is a confirmed loan that leaves within a week, or whose start
has passed without a checkout; « En retard », a loan out past its end. A
committee loan has neither checkout nor return: it stays « Usage comité ».
"""

import datetime as dt

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
