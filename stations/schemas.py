from ninja import Schema

from core.schemas import InputSchema


class StationIn(InputSchema):
    """A station as the board writes it. Its values are checked by the model."""

    name: str
    description: str
    required_count: int


class StationOrderIn(InputSchema):
    # The ids of the event's stations, each once, in their new order.
    stations: list[int]


class AssignmentIn(InputSchema):
    name: str
    # Left empty, the volunteer has no particular role.
    role: str


class AssignmentOut(Schema):
    id: int
    name: str
    role: str


class StationOut(Schema):
    """A station, the people at it, and whether there are enough of them."""

    id: int
    name: str
    description: str
    required_count: int
    assigned_count: int
    # Enough people stand at it, more being allowed.
    complete: bool
    assignments: list[AssignmentOut]


class StationBoardOut(Schema):
    """The stations of an event and their totals: a bounded aggregate."""

    stations: list[StationOut]
    required_count: int
    assigned_count: int
    # The places still to fill, station by station: one station's surplus
    # never fills another's shortfall.
    open_places: int
    # Every station is complete; an event without stations is not.
    complete: bool
