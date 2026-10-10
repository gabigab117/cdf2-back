import datetime as dt

from ninja import Schema

from core.schemas import InputSchema


class TicketTypeIn(InputSchema):
    name: str


class TicketTypeOut(Schema):
    id: int
    name: str


class ReservationLineIn(InputSchema):
    # The id of a type of place of the event.
    ticket_type: int
    quantity: int


class ReservationIn(InputSchema):
    """A reservation as the board writes it: whole, every key required."""

    name: str
    # « table, placement… »: never a health detail.
    note: str
    # The places by type: a type without places is left out.
    lines: list[ReservationLineIn]


class CapacityIn(InputSchema):
    # None: no limit.
    capacity: int | None


class ReservationLineOut(Schema):
    # The id of its type of place.
    ticket_type: int
    quantity: int

    @staticmethod
    def resolve_ticket_type(line):
        return line.ticket_type_id


class ReservationOut(Schema):
    """A reservation, its places by type and their total."""

    id: int
    name: str
    note: str
    created_at: dt.datetime
    lines: list[ReservationLineOut]
    seats: int


class TicketTypeStatsOut(Schema):
    id: int
    name: str
    # The places reserved of this type, and by how many reservations.
    seats: int
    reservations: int


class ReservationStatsOut(Schema):
    """The figures of an event's reservations: a bounded aggregate."""

    # None: no limit.
    capacity: int | None
    reservations: int
    seats: int
    # None without a capacity; never below zero.
    remaining: int | None
    ticket_types: list[TicketTypeStatsOut]
