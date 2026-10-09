import datetime as dt

from ninja import FilterSchema, Schema
from pydantic import AwareDatetime

from accounts.schemas import BoardMemberOut
from core.schemas import InputSchema
from events.models import EventCategory, PracticalInfoIcon


class ProgrammeItemIn(InputSchema):
    time: dt.time
    title: str
    description: str


class PracticalInfoIn(InputSchema):
    icon: PracticalInfoIcon
    title: str
    text: str


class EventIn(InputSchema):
    """An event as the board writes it: whole, every key required.

    A key left out never erases a value, the programme above all. The lists are
    given in display order and replace the previous ones. The values themselves
    are checked by the model, whose messages are in French.
    """

    title: str
    # Left empty, it is derived from the title and the year.
    slug: str
    category: EventCategory
    # A date without its time zone is refused.
    starts_at: AwareDatetime
    ends_at: AwareDatetime | None
    start_label: str
    venue_name: str
    venue_address: str
    latitude: float | None
    longitude: float | None
    price_label: str
    price_detail: str
    summary: str
    published: bool
    # The id of a board member.
    lead: int | None
    # The id of another event.
    previous_edition: int | None
    programme: list[ProgrammeItemIn]
    practical_infos: list[PracticalInfoIn]


class EventFilters(FilterSchema):
    category: EventCategory | None = None
    published: bool | None = None


# Plain Schemas rather than ModelSchemas, which would publish the fields that
# may be blank as optional and nullable.
class EventItemOut(Schema):
    """An event in a list."""

    id: int
    title: str
    slug: str
    category: EventCategory
    starts_at: dt.datetime
    ends_at: dt.datetime | None
    start_label: str
    venue_name: str
    published: bool


class ProgrammeItemOut(Schema):
    time: dt.time
    title: str
    description: str


class PracticalInfoOut(Schema):
    icon: PracticalInfoIcon
    title: str
    text: str


class EventOut(EventItemOut):
    """An event with all its content, in display order."""

    venue_address: str
    latitude: float | None
    longitude: float | None
    price_label: str
    price_detail: str
    summary: str
    lead: BoardMemberOut | None
    previous_edition: EventItemOut | None
    programme: list[ProgrammeItemOut]
    practical_infos: list[PracticalInfoOut]
    updated_at: dt.datetime


# The public site's own schemas. No board schema is reused for the site: a field
# added for the board would reach it. None of them names a person.


class PublicEventFilters(FilterSchema):
    category: EventCategory | None = None


class PublicEventItemOut(Schema):
    """An event of the agenda."""

    slug: str
    title: str
    category: EventCategory
    starts_at: dt.datetime
    ends_at: dt.datetime | None
    start_label: str
    venue_name: str
    price_label: str
    price_detail: str


class PublicProgrammeItemOut(Schema):
    time: dt.time
    title: str
    description: str


class PublicPracticalInfoOut(Schema):
    icon: PracticalInfoIcon
    title: str
    text: str


class PublicEventOut(PublicEventItemOut):
    """An event's page on the site, followed by the next events of the agenda."""

    venue_address: str
    latitude: float | None
    longitude: float | None
    summary: str
    programme: list[PublicProgrammeItemOut]
    practical_infos: list[PublicPracticalInfoOut]
    next_events: list[PublicEventItemOut]


class AgendaOut(Schema):
    """What the site shows around its agenda."""

    # The categories of its events, in their usual order: the filter offers
    # those only.
    categories: list[EventCategory]
    # When the board last changed one of its events; null for an empty agenda.
    updated_at: dt.datetime | None
