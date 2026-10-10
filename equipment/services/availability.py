"""What equipment is free over a period (A15): what each equipment counts, what
the loans take of it at their daily peak, and what remains.

A loan takes its equipment over its days, both counted: one that brings it back
on a day and one that takes it the same day are in conflict. A loan out holds
it from the day it left, even before its start, and until today when it is
overdue: its effective dates (A15, decisions of 10/10/2026). The peak comes
from a sweep of the loans' starts and ends, never from a loop over the days.

The services that write a loan lock its equipment first (select_for_update, in
the order of their keys): what they read here cannot change before they write.
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import groupby

from django.core.exceptions import ValidationError
from django.db.models import Case, F, Q, QuerySet, Value, When
from django.db.models.functions import Greatest, Least
from django.utils import timezone

from equipment.models import LOAN_MAX_DAYS, Equipment, Loan, LoanLine, LoanStatus
from equipment.services.states import loan_state

ONE_DAY = dt.timedelta(days=1)


@dataclass(frozen=True)
class Conflict:
    """What one loan takes of one equipment, over the days it holds it."""

    loan: Loan
    quantity: int
    # Its effective days.
    start: dt.date
    end: dt.date


@dataclass(frozen=True)
class Availability:
    """What one equipment offers over a period."""

    equipment: Equipment
    # The most pieces the loans take on a single day of the period.
    taken: int
    # What remains for another loan, never below zero.
    free: int
    # The loans that take it over the period, the first to start first.
    conflicts: list[Conflict]


@dataclass(frozen=True)
class AvailabilityReport:
    """What every equipment offers over a period: a bounded aggregate (A7)."""

    start: dt.date
    end: dt.date
    items: list[Availability]


@dataclass(frozen=True)
class Shortage:
    """The days the loans take more of an equipment than it offers, from today on."""

    equipment: Equipment
    # The first of those days.
    day: dt.date
    # What the equipment offers: its pieces, those under repair aside.
    offered: int
    # The most pieces the loans take on one of those days.
    taken: int
    # The loans that hold it on those days, the first to start first.
    loans: list[Loan]


def check_period(start: dt.date, end: dt.date) -> None:
    """Refuse a period no loan could cover: backwards, or longer than a loan."""
    days = (end - start).days + 1
    if days < 1:
        raise ValidationError("La date de retour est avant la date de sortie.")
    if days > LOAN_MAX_DAYS:
        raise ValidationError(f"Un prêt dure au plus {LOAN_MAX_DAYS} jours.")


def holding_lines(today: dt.date) -> QuerySet[LoanLine]:
    """The lines of the loans that hold their equipment, confirmed or out, with
    the days they hold it: effective_start and effective_end.
    """
    out = Q(loan__status=LoanStatus.OUT)
    return LoanLine.objects.filter(
        loan__status__in=[LoanStatus.CONFIRMED, LoanStatus.OUT]
    ).annotate(
        effective_start=Case(
            When(out, then=Least("loan__start_date", Value(today))),
            default=F("loan__start_date"),
        ),
        effective_end=Case(
            When(out, then=Greatest("loan__end_date", Value(today))),
            default=F("loan__end_date"),
        ),
    )


def availability(
    equipment: Iterable[Equipment],
    start: dt.date,
    end: dt.date,
    *,
    exclude_loan: int | None = None,
    today: dt.date | None = None,
) -> list[Availability]:
    """What each equipment offers between two days, both counted, leaving out
    the loan being edited, if any.
    """
    today = today or timezone.localdate()
    equipment = list(equipment)
    lines = holding_lines(today).filter(
        equipment__in=equipment, effective_start__lte=end, effective_end__gte=start
    )
    if exclude_loan is not None:
        lines = lines.exclude(loan_id=exclude_loan)
    conflicts = _conflicts(lines, today)
    report = []
    for item in equipment:
        held = conflicts[item.pk]
        taken = _peak(held, start, end)
        offered = item.total_quantity - item.repair_quantity
        report.append(Availability(item, taken, max(offered - taken, 0), held))
    return report


def availability_report(
    equipment: Iterable[Equipment], start: dt.date, end: dt.date, exclude_loan: int | None
) -> AvailabilityReport:
    """What every equipment offers over the period of a loan being written."""
    check_period(start, end)
    return AvailabilityReport(
        start, end, availability(equipment, start, end, exclude_loan=exclude_loan)
    )


def shortages(equipment: Iterable[Equipment], *, today: dt.date | None = None) -> list[Shortage]:
    """The equipment the loans take more of than it offers, from today on: one
    entry per equipment short.

    The values of the equipment given count, saved or not: the inventory checks
    a change, such as more pieces under repair, before it writes it.
    """
    today = today or timezone.localdate()
    equipment = list(equipment)
    lines = holding_lines(today).filter(equipment__in=equipment, effective_end__gte=today)
    conflicts = _conflicts(lines, today)
    report = []
    for item in equipment:
        shortage = _shortage(item, conflicts[item.pk], today)
        if shortage is not None:
            report.append(shortage)
    return report


def _conflicts(lines: QuerySet[LoanLine], today: dt.date) -> dict[int, list[Conflict]]:
    """The hold of the loans on each equipment, by its id, the first to start
    first. Each loan carries its state, as a list of loans does.
    """
    conflicts: dict[int, list[Conflict]] = defaultdict(list)
    for line in lines.select_related("loan__event").order_by("effective_start", "loan_id"):
        line.loan.state = loan_state(line.loan, today)
        conflicts[line.equipment_id].append(
            Conflict(line.loan, line.quantity, line.effective_start, line.effective_end)
        )
    return conflicts


def _changes(
    conflicts: list[Conflict], start: dt.date, end: dt.date
) -> list[tuple[dt.date, int, int]]:
    """When the loans take their pieces and give them back within a period, in
    order, with the place of their loan in the list: a loan takes them on its
    first day and gives them back the day after its last. On a same day, what is
    given back comes first: its loan has ended.
    """
    return sorted(
        change
        for index, conflict in enumerate(conflicts)
        for change in (
            (max(conflict.start, start), conflict.quantity, index),
            (min(conflict.end, end) + ONE_DAY, -conflict.quantity, index),
        )
    )


def _peak(conflicts: list[Conflict], start: dt.date, end: dt.date) -> int:
    """The most pieces the loans take on a single day of the period."""
    peak = taken = 0
    for _day, change, _index in _changes(conflicts, start, end):
        taken += change
        peak = max(peak, taken)
    return peak


def _shortage(item: Equipment, conflicts: list[Conflict], today: dt.date) -> Shortage | None:
    """The days, from today on, the loans take more of an equipment than it
    offers, if any.
    """
    offered = item.total_quantity - item.repair_quantity
    last = max((conflict.end for conflict in conflicts), default=today)
    holding: set[int] = set()
    short: set[int] = set()
    first_day = None
    taken = most = 0
    for day, changes in groupby(_changes(conflicts, today, last), key=lambda change: change[0]):
        for _day, change, index in changes:
            taken += change
            if change > 0:
                holding.add(index)
            else:
                holding.discard(index)
        if taken > offered:
            first_day = first_day or day
            most = max(most, taken)
            short |= holding
    if first_day is None:
        return None
    return Shortage(item, first_day, offered, most, [conflicts[i].loan for i in sorted(short)])
