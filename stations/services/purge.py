"""The purge of the volunteers' names (A9), every night, two years after their
event: the stations keep their people, and their counts with them.
"""

import datetime as dt

from dateutil.relativedelta import relativedelta

from core.text import ERASED_NAME
from events.services.periods import events_over_by
from stations.models import Assignment

VOLUNTEER_RETENTION = relativedelta(years=2)


def purge_volunteers(today: dt.date) -> int:
    """Erase the names of the volunteers whose retention period is over by
    today: how many were erased.
    """
    return (
        Assignment.objects.filter(station__event__in=events_over_by(today - VOLUNTEER_RETENTION))
        .exclude(name=ERASED_NAME)
        .update(name=ERASED_NAME)
    )
