"""The fictitious equipment and loans of the mockup, which the preproduction
shows (`seed_demo`).

The loans keep their place around today as around the mockup's day, Thursday
1 October: two returned, one out, one to prepare, two confirmed, and the
equipment the committee keeps for three of its demo events, from the day
before to the day after. They are written through the services, as a member
would: a loan that would take more than is free is left out, as the API
would refuse it.
"""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from equipment.models import Equipment, EquipmentCategory, Loan, LoanBorrowerType
from equipment.schemas import EquipmentIn, LoanIn, LoanLineIn, LoanReturnIn, ReturnLineIn
from equipment.services.inventory import create_equipment, update_equipment
from equipment.services.lifecycle import check_out, return_loan
from equipment.services.loans import create_loan
from events.models import Event

_CATEGORIES = EquipmentCategory

# Its name, category, place, pieces, pieces under repair, value of a piece and
# repair note, before the loans: the bench damaged at the school's fête goes
# under repair with its return.
DEMO_EQUIPMENT = [
    (
        "Tables pliantes 180 cm",
        _CATEGORIES.FURNITURE,
        "Local du comité · rack A",
        24,
        1,
        "60",
        "1 table au pied voilé, à redresser.",
    ),
    (
        "Bancs pliants",
        _CATEGORIES.FURNITURE,
        "Local du comité · rack A",
        40,
        1,
        "35",
        "1 assise fendue.",
    ),
    ("Chaises empilables", _CATEGORIES.FURNITURE, "Réserve de la salle des fêtes", 80, 0, "15", ""),
    ("Mange-debout", _CATEGORIES.FURNITURE, "Réserve de la salle des fêtes", 6, 0, "45", ""),
    (
        "Barnums 3 × 3 m",
        _CATEGORIES.MARQUEES,
        "Garage communal",
        4,
        1,
        "250",
        "Toile déchirée sur un côté. Devis de réparation demandé.",
    ),
    ("Barnums 3 × 6 m", _CATEGORIES.MARQUEES, "Garage communal", 2, 0, "420", ""),
    ("Lestes de barnum 15 kg", _CATEGORIES.MARQUEES, "Garage communal", 16, 0, "20", ""),
    (
        "Enceintes sur pied",
        _CATEGORIES.SOUND_AND_LIGHT,
        "Local du comité · armoire",
        2,
        0,
        "300",
        "",
    ),
    (
        "Guirlandes guinguette 20 m",
        _CATEGORIES.SOUND_AND_LIGHT,
        "Local du comité · armoire",
        6,
        0,
        "40",
        "",
    ),
    (
        "Rallonges 25 m",
        _CATEGORIES.SOUND_AND_LIGHT,
        "Local du comité · armoire",
        10,
        1,
        "25",
        "1 rallonge à la prise endommagée.",
    ),
    (
        "Percolateurs 100 tasses",
        _CATEGORIES.KITCHEN,
        "Réserve de la salle des fêtes",
        2,
        0,
        "90",
        "",
    ),
    (
        "Réfrigérateur vitrine",
        _CATEGORIES.KITCHEN,
        "Réserve de la salle des fêtes",
        1,
        0,
        "400",
        "",
    ),
    ("Barrières de ville", _CATEGORIES.STREET_AND_GAMES, "Garage communal", 20, 0, "50", ""),
    (
        "Jeux en bois (lot de 8)",
        _CATEGORIES.STREET_AND_GAMES,
        "Local du comité · rack B",
        1,
        0,
        "350",
        "",
    ),
]


@dataclass(frozen=True)
class DemoLoan:
    """A loan of the mockup, its days counted from today."""

    borrower: str
    kind: LoanBorrowerType
    purpose: str
    starts: int
    ends: int
    # Its step: "returned", "out", or confirmed.
    step: str
    pieces: dict[str, int]
    # What came back damaged, for a loan returned.
    damaged: dict[str, int] | None = None


_TYPES = LoanBorrowerType

DEMO_LOANS = [
    DemoLoan(
        "Mairie",
        _TYPES.MUNICIPALITY,
        "Journées du patrimoine",
        -13,
        -10,
        "returned",
        {"Barrières de ville": 20, "Chaises empilables": 10},
    ),
    DemoLoan(
        "Parents d’élèves",
        _TYPES.ASSOCIATION,
        "Fête de l’école",
        -6,
        -3,
        "returned",
        {"Bancs pliants": 12, "Tables pliantes 180 cm": 6, "Barnums 3 × 3 m": 1},
        damaged={"Bancs pliants": 1},
    ),
    DemoLoan(
        "École du village",
        _TYPES.ASSOCIATION,
        "Cross",
        -1,
        1,
        "out",
        {"Tables pliantes 180 cm": 4, "Barnums 3 × 3 m": 2, "Enceintes sur pied": 1},
    ),
    DemoLoan(
        "M. Petit",
        _TYPES.INDIVIDUAL,
        "Anniversaire",
        2,
        4,
        "confirmed",
        {"Barnums 3 × 6 m": 1, "Chaises empilables": 30, "Guirlandes guinguette 20 m": 2},
    ),
    DemoLoan(
        "Club de football",
        _TYPES.ASSOCIATION,
        "Tournoi jeunes",
        15,
        17,
        "confirmed",
        {"Barnums 3 × 3 m": 2, "Tables pliantes 180 cm": 8, "Bancs pliants": 16},
    ),
    DemoLoan(
        "Comité des fêtes voisin",
        _TYPES.ASSOCIATION,
        "Fête de la pomme",
        22,
        25,
        "confirmed",
        {"Barrières de ville": 20, "Lestes de barnum 15 kg": 8},
    ),
]

# The equipment the committee keeps for its demo events, by their title.
DEMO_RESERVATIONS = {
    "Halloween des enfants": {
        "Tables pliantes 180 cm": 8,
        "Bancs pliants": 16,
        "Barnums 3 × 3 m": 2,
        "Guirlandes guinguette 20 m": 6,
        "Enceintes sur pied": 1,
    },
    "Loto d’automne": {
        "Tables pliantes 180 cm": 20,
        "Chaises empilables": 80,
        "Enceintes sur pied": 1,
    },
    "Marché de Noël": {
        "Barnums 3 × 3 m": 3,
        "Barnums 3 × 6 m": 2,
        "Guirlandes guinguette 20 m": 6,
        "Rallonges 25 m": 8,
        "Lestes de barnum 15 kg": 16,
    },
}


@dataclass(frozen=True)
class DemoInventory:
    """What the seed wrote: its equipment, and its loans."""

    equipment: list[Equipment]
    loans: list[Loan]


@transaction.atomic
def seed_demo_equipment(today: dt.date) -> DemoInventory:
    """Write the equipment and the loans of the mockup around `today`.

    An equipment already written is found by its name and rewritten; the loans
    of the demonstration are written anew. A loan typed by hand stays.
    """
    Loan.objects.filter(borrower_name__in=[demo.borrower for demo in DEMO_LOANS]).delete()
    Loan.objects.filter(event__title__in=DEMO_RESERVATIONS).delete()
    equipment = {name: _equipment(name, *values) for name, *values in DEMO_EQUIPMENT}
    loans = [
        loan
        for loan in (
            *(_reservation(event, equipment) for event in _demo_events(today)),
            *(_loan(demo, equipment, today) for demo in DEMO_LOANS),
        )
        if loan is not None
    ]
    return DemoInventory(list(equipment.values()), loans)


def _equipment(
    name: str, category: str, place: str, total: int, repair: int, value: str, note: str
) -> Equipment:
    data = EquipmentIn(
        name=name,
        category=category,
        storage_location=place,
        total_quantity=total,
        repair_quantity=repair,
        unit_value=Decimal(value),
        repair_note=note,
    )
    existing = Equipment.objects.filter(name__iexact=name).first()
    return create_equipment(data) if existing is None else update_equipment(existing, data)


def _demo_events(today: dt.date) -> list[Event]:
    """The demo events to come that keep equipment."""
    start_of_day = timezone.make_aware(dt.datetime.combine(today, dt.time.min))
    upcoming = Event.objects.filter(title__in=DEMO_RESERVATIONS, starts_at__gte=start_of_day)
    return list(upcoming.order_by("starts_at"))


def _lines(pieces: dict[str, int], equipment: dict[str, Equipment]) -> list[LoanLineIn]:
    return [
        LoanLineIn(equipment=equipment[name].pk, quantity=count) for name, count in pieces.items()
    ]


def _reservation(event: Event, equipment: dict[str, Equipment]) -> Loan | None:
    day = timezone.localtime(event.starts_at).date()
    data = LoanIn(
        borrower_type=LoanBorrowerType.COMMITTEE,
        borrower_name="",
        purpose="",
        phone="",
        start_date=day - dt.timedelta(days=1),
        end_date=day + dt.timedelta(days=1),
        deposit_amount=None,
        event=event.pk,
        notes="",
        lines=_lines(DEMO_RESERVATIONS[event.title], equipment),
    )
    return _written(lambda: create_loan(data, None))


def _loan(demo: DemoLoan, equipment: dict[str, Equipment], today: dt.date) -> Loan | None:
    data = LoanIn(
        borrower_type=demo.kind,
        borrower_name=demo.borrower,
        purpose=demo.purpose,
        phone="",
        start_date=today + dt.timedelta(days=demo.starts),
        end_date=today + dt.timedelta(days=demo.ends),
        deposit_amount=None,
        event=None,
        notes="",
        lines=_lines(demo.pieces, equipment),
    )

    def write() -> Loan:
        loan = create_loan(data, None)
        if demo.step == "confirmed":
            return loan
        loan = check_out(loan)
        if demo.step == "out":
            return loan
        damaged = demo.damaged or {}
        lines = [
            ReturnLineIn(
                line=line.pk, damaged_quantity=damaged[line.equipment.name], missing_quantity=0
            )
            for line in loan.lines.all()
            if line.equipment.name in damaged
        ]
        return return_loan(loan, LoanReturnIn(lines=lines)).loan

    return _written(write)


def _written(write: Callable[[], Loan]) -> Loan | None:
    """The loan written, or none if it would take more than is free."""
    try:
        with transaction.atomic():
            return write()
    except ValidationError:
        return None
