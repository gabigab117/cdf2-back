import datetime as dt
from decimal import Decimal

from ninja import Schema

from core.schemas import InputSchema
from equipment.models import EquipmentCategory, LoanBorrowerType, LoanState


class AvailabilityQuery(Schema):
    """The period of a loan, both days counted, and the loan being edited."""

    start: dt.date
    end: dt.date
    # The id of the loan being edited: the pieces it takes are not counted.
    exclude_loan: int | None = None


class EquipmentIn(InputSchema):
    """An equipment as the board writes it: whole, every key required.

    Its values are checked by the model, whose messages are in French.
    """

    name: str
    category: EquipmentCategory
    storage_location: str
    total_quantity: int
    repair_quantity: int
    unit_value: Decimal | None
    repair_note: str


class EquipmentOut(Schema):
    """An equipment of the inventory."""

    id: int
    name: str
    category: EquipmentCategory
    storage_location: str
    total_quantity: int
    # Pieces out of use until mended: never lent.
    repair_quantity: int
    # What replacing one piece would cost, if known.
    unit_value: Decimal | None
    repair_note: str


class LoanBriefOut(Schema):
    """A loan, as a line of a list or of a planning names it."""

    id: int
    # None for a committee loan: « réservation interne ».
    number: str | None
    # Its borrower, or the title of its event for a committee loan.
    display_name: str
    purpose: str
    borrower_type: LoanBorrowerType
    state: LoanState
    start_date: dt.date
    end_date: dt.date


class LoanConflictOut(Schema):
    """A loan that takes the equipment over the period, and how many pieces."""

    loan: LoanBriefOut
    quantity: int


class EquipmentAvailabilityOut(Schema):
    """What one equipment offers over the period."""

    equipment: EquipmentOut
    # The most pieces the loans take on a single day of the period.
    taken: int
    # What remains for the loan being written.
    free: int
    # The loans that take it, the first to start first.
    conflicts: list[LoanConflictOut]


class AvailabilityOut(Schema):
    """What every equipment offers over a period: a bounded aggregate (A7)."""

    start: dt.date
    end: dt.date
    items: list[EquipmentAvailabilityOut]


class InventoryTotalsOut(Schema):
    """The figures under the inventory's title."""

    references: int
    # The equipment some pieces of which are taken today.
    taken_today: int
    pieces_under_repair: int


class EquipmentCountsOut(Schema):
    """How many equipment each category holds: the chips of the inventory."""

    total: int
    furniture: int
    marquees: int
    sound_and_light: int
    kitchen: int
    street_and_games: int


class InventoryOut(Schema):
    """What each equipment offers today, in the inventory's order: a bounded
    aggregate (A7).
    """

    day: dt.date
    items: list[EquipmentAvailabilityOut]
    totals: InventoryTotalsOut
    counts: EquipmentCountsOut


class OccupancyOut(Schema):
    """The loans that take an equipment over the weeks to come."""

    start: dt.date
    end: dt.date
    # The first to start first.
    loans: list[LoanConflictOut]
