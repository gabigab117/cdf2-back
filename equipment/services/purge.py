"""The purge of the borrowers' personal data (A9), every night: their phone
three months after the return, the name of a person and the notes of their loan
a year after. A loan the board has not closed keeps everything.
"""

import datetime as dt
from dataclasses import dataclass

from dateutil.relativedelta import relativedelta
from django.db.models import Q

from core.text import ERASED_NAME
from equipment.models import Loan, LoanBorrowerType, LoanStatus

PHONE_RETENTION = relativedelta(months=3)
NAME_RETENTION = relativedelta(years=1)


@dataclass(frozen=True)
class LoanPurge:
    """How many loans lost their borrower's phone, and their borrower's name."""

    phones: int
    names: int


def purge_loans(today: dt.date) -> LoanPurge:
    """Erase the phones, then the names of persons and the notes of their loans,
    whose retention period is over by today. The name gives way to a mention: a
    loan to a third party keeps a borrower.
    """
    phones = (
        Loan.objects.filter(_closed_by(today - PHONE_RETENTION)).exclude(phone="").update(phone="")
    )
    names = (
        Loan.objects.filter(
            _closed_by(today - NAME_RETENTION), borrower_type=LoanBorrowerType.INDIVIDUAL
        )
        .exclude(borrower_name=ERASED_NAME, notes="")
        .update(borrower_name=ERASED_NAME, notes="")
    )
    return LoanPurge(phones=phones, names=names)


def _closed_by(day: dt.date) -> Q:
    """The loans closed by the end of a day: returned on that day in Paris, or
    before, as only a returned loan has a return date; or cancelled with their
    return planned by then, as they have no return to count from.
    """
    return Q(returned_at__date__lte=day) | Q(status=LoanStatus.CANCELLED, end_date__lte=day)
