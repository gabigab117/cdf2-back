"""The ledger of the mockup, on its day, Thursday 1 October 2026: the reference
of the results (Tresorerie.dc.html). Fictitious, like every name of the mockup.

The mockup lists ten entries, and adds the totals of entries it does not list:
each event's, and 40,50 € of general expenses. Those are written here as
entries too.
"""

import datetime as dt
from decimal import Decimal

from tests.accounts.factories import BoardMemberFactory
from tests.events.factories import EventFactory
from tests.treasury.factories import LedgerEntryFactory
from treasury.models import LedgerCategory, LedgerEntryKind, LedgerPaymentMethod

INCOME = Decimal("11490.00")
EXPENSE = Decimal("6921.25")
RESULT = Decimal("4568.75")

# Its title and its start.
EVENTS = {
    "loto": ("Loto de printemps", "2026-03-21T19:00:00+01:00"),
    "oeufs": ("Chasse aux œufs", "2026-04-05T10:00:00+02:00"),
    "stjean": ("Feu de la Saint-Jean", "2026-06-20T21:00:00+02:00"),
    "juillet": ("Fête du 14 juillet", "2026-07-14T18:00:00+02:00"),
    "brocante": ("Brocante", "2026-09-13T07:00:00+02:00"),
    "halloween": ("Halloween des enfants", "2026-10-31T15:00:00+01:00"),
    "loto_automne": ("Loto d’automne", "2026-11-15T14:00:00+01:00"),
    "noel": ("Marché de Noël", "2026-12-13T10:00:00+01:00"),
}

IN = LedgerEntryKind.INCOME
OUT = LedgerEntryKind.EXPENSE
C = LedgerCategory
M = LedgerPaymentMethod

# Its event, date, kind, label, amount, category, and payment method or the
# first name of the member who advanced it.
ENTRIES = [
    # The totals the mockup does not list.
    ("loto", "2026-03-21", IN, "Recettes du loto", "1920.00", C.TICKETS, M.CASH),
    ("loto", "2026-03-15", OUT, "Lots du loto", "1040.00", C.PRIZES, M.CHEQUE),
    ("oeufs", "2026-04-01", OUT, "Œufs en chocolat", "310.00", C.FOOD, M.CHEQUE),
    ("stjean", "2026-06-20", IN, "Buvette", "1480.00", C.BAR, M.CASH),
    ("stjean", "2026-06-18", OUT, "Bois et sécurité", "1120.00", C.MISC, M.TRANSFER),
    ("juillet", "2026-07-14", IN, "Buvette et repas", "2350.00", C.BAR, M.CASH),
    ("juillet", "2026-07-10", OUT, "Feu d’artifice", "2910.00", C.MISC, M.TRANSFER),
    ("brocante", "2026-09-01", OUT, "Affiches", "598.70", C.MISC, M.CHEQUE),
    (None, "2026-08-31", OUT, "Frais de tenue", "40.50", C.BANK_FEES, M.DIRECT_DEBIT),
    # The ten entries of the journal, the latest first.
    ("halloween", "2026-09-30", OUT, "Courses goûter", "47.85", C.FOOD, "Sophie"),
    (
        "halloween",
        "2026-09-29",
        OUT,
        "Fête & Déco — décoration",
        "147.40",
        C.DECORATION,
        M.ASSOCIATION_CARD,
    ),
    (None, "2026-09-28", IN, "Cotisations des membres", "120.00", C.MEMBERSHIP_FEES, M.CASH),
    ("brocante", "2026-09-16", IN, "Recette buvette", "1862.50", C.BAR, M.CASH),
    ("brocante", "2026-09-15", IN, "Emplacements exposants", "2257.50", C.PITCHES, M.TRANSFER),
    (
        "brocante",
        "2026-09-14",
        OUT,
        "Location Pro 60 — friteuse",
        "95.00",
        C.EQUIPMENT_RENTAL,
        M.CHEQUE,
    ),
    ("brocante", "2026-09-12", OUT, "Courses buvette", "286.30", C.DRINKS, "Marc"),
    (None, "2026-09-10", OUT, "Frais bancaires", "13.50", C.BANK_FEES, M.DIRECT_DEBIT),
    (None, "2026-09-05", OUT, "Assurance des manifestations", "312.00", C.INSURANCE, M.TRANSFER),
    (None, "2026-09-01", IN, "Subvention municipale", "1500.00", C.GRANT, M.TRANSFER),
]


def build_mockup():
    """Write the events and the entries of the mockup: the events by their key."""
    events = {
        key: EventFactory(title=title, starts_at=dt.datetime.fromisoformat(starts_at))
        for key, (title, starts_at) in EVENTS.items()
    }
    members = {
        "Sophie": BoardMemberFactory(first_name="Sophie", last_name="Lambert"),
        "Marc": BoardMemberFactory(first_name="Marc", last_name="Durand"),
    }
    for event, date, kind, label, amount, category, paid in ENTRIES:
        advanced_by = members.get(paid)
        LedgerEntryFactory(
            event=events[event] if event else None,
            date=dt.date.fromisoformat(date),
            kind=kind,
            label=label,
            amount=Decimal(amount),
            category=category,
            payment_method=M.ADVANCE if advanced_by else paid,
            advanced_by=advanced_by,
        )
    return events
