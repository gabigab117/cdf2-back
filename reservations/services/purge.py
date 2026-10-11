"""The purge of the reservations' personal data (A9), every night: the name and
the remark of a reservation three months after its event. Its places stay, and
the event's totals with them.
"""

import datetime as dt

from dateutil.relativedelta import relativedelta

from core.text import ERASED_NAME
from events.services.periods import events_over_by
from reservations.models import Reservation

RESERVATION_RETENTION = relativedelta(months=3)


def purge_reservations(today: dt.date) -> int:
    """Erase the name and the remark of the reservations whose retention period
    is over by today: how many were erased.
    """
    return (
        Reservation.objects.filter(event__in=events_over_by(today - RESERVATION_RETENTION))
        .exclude(name=ERASED_NAME, note="")
        .update(name=ERASED_NAME, note="")
    )
