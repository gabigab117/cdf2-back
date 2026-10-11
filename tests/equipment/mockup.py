"""The equipment and loans of the mockup, around its day, Thursday 1 October
2026: the reference of the availability rule (A15). Fictitious, like every name
of the mockup.
"""

import datetime as dt
from dataclasses import dataclass

from django.utils import timezone

from equipment.models import LoanBorrowerType, LoanStatus
from tests.equipment.factories import (
    CommitteeLoanFactory,
    EquipmentFactory,
    LoanFactory,
    LoanLineFactory,
)
from tests.events.factories import EventFactory

TODAY = dt.date(2026, 10, 1)

# Its name, pieces and pieces under repair.
EQUIPMENT = {
    "tables": ("Tables pliantes 180 cm", 24, 1),
    "bancs": ("Bancs pliants", 40, 2),
    "chaises": ("Chaises empilables", 80, 0),
    "mange": ("Mange-debout", 6, 0),
    "b33": ("Barnums 3 × 3 m", 4, 1),
    "b36": ("Barnums 3 × 6 m", 2, 0),
    "lestes": ("Lestes de barnum 15 kg", 16, 0),
    "enceinte": ("Enceintes sur pied", 2, 0),
    "guirlandes": ("Guirlandes guinguette 20 m", 6, 0),
    "rallonges": ("Rallonges 25 m", 10, 1),
    "perco": ("Percolateurs 100 tasses", 2, 0),
    "frigo": ("Réfrigérateur vitrine", 1, 0),
    "barrieres": ("Barrières de ville", 20, 0),
    "jeux": ("Jeux en bois (lot de 8)", 1, 0),
}

_TYPES = LoanBorrowerType
_STATUSES = LoanStatus

# The loans to someone: their borrower, type, purpose, days, status and pieces.
LOANS = {
    "mairie": (
        "Mairie",
        _TYPES.MUNICIPALITY,
        "Journées du patrimoine",
        ("2026-09-18", "2026-09-21"),
        _STATUSES.RETURNED,
        {"barrieres": 20, "chaises": 10},
    ),
    "ecole_fete": (
        "Parents d’élèves",
        _TYPES.ASSOCIATION,
        "Fête de l’école",
        ("2026-09-25", "2026-09-28"),
        _STATUSES.RETURNED,
        {"bancs": 12, "tables": 6, "b33": 1},
    ),
    "cross": (
        "École du village",
        _TYPES.ASSOCIATION,
        "Cross",
        ("2026-09-30", "2026-10-02"),
        _STATUSES.OUT,
        {"tables": 4, "b33": 2, "enceinte": 1},
    ),
    "anniversaire": (
        "M. Petit",
        _TYPES.INDIVIDUAL,
        "Anniversaire",
        ("2026-10-03", "2026-10-05"),
        _STATUSES.CONFIRMED,
        {"b36": 1, "chaises": 30, "guirlandes": 2},
    ),
    "tournoi": (
        "Club de football",
        _TYPES.ASSOCIATION,
        "Tournoi jeunes",
        ("2026-10-16", "2026-10-18"),
        _STATUSES.CONFIRMED,
        {"b33": 2, "tables": 8, "bancs": 16},
    ),
    "pomme": (
        "Comité des fêtes voisin",
        _TYPES.ASSOCIATION,
        "Fête de la pomme",
        ("2026-10-23", "2026-10-26"),
        _STATUSES.CONFIRMED,
        {"barrieres": 20, "lestes": 8},
    ),
}

# The equipment the committee keeps for its events: their title, days and pieces.
COMMITTEE_LOANS = {
    "halloween": (
        "Halloween des enfants",
        ("2026-10-30", "2026-11-01"),
        {"tables": 8, "bancs": 16, "b33": 2, "guirlandes": 6, "enceinte": 1},
    ),
    "loto": (
        "Loto d’automne",
        ("2026-11-14", "2026-11-15"),
        {"tables": 20, "chaises": 80, "enceinte": 1},
    ),
    "noel": (
        "Marché de Noël",
        ("2026-12-11", "2026-12-13"),
        {"b33": 3, "b36": 2, "guirlandes": 6, "rallonges": 8, "lestes": 16},
    ),
}


@dataclass(frozen=True)
class Mockup:
    equipment: dict
    loans: dict


def _day(iso):
    return dt.date.fromisoformat(iso)


def _lines(loan, pieces, equipment):
    for key, quantity in pieces.items():
        LoanLineFactory(loan=loan, equipment=equipment[key], quantity=quantity)


def build_mockup():
    """Write the equipment and the loans of the mockup."""
    equipment = {
        key: EquipmentFactory(name=name, total_quantity=total, repair_quantity=repair)
        for key, (name, total, repair) in EQUIPMENT.items()
    }
    loans = {}
    for key, (borrower, kind, purpose, (start, end), status, pieces) in LOANS.items():
        returned = timezone.make_aware(dt.datetime.combine(_day(end), dt.time(18)))
        loans[key] = LoanFactory(
            borrower_name=borrower,
            borrower_type=kind,
            purpose=purpose,
            start_date=_day(start),
            end_date=_day(end),
            status=status,
            returned_at=returned if status == LoanStatus.RETURNED else None,
        )
        _lines(loans[key], pieces, equipment)
    for key, (title, (start, end), pieces) in COMMITTEE_LOANS.items():
        loans[key] = CommitteeLoanFactory(
            event=EventFactory(title=title), start_date=_day(start), end_date=_day(end)
        )
        _lines(loans[key], pieces, equipment)
    return Mockup(equipment, loans)
