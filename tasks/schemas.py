import datetime as dt

from ninja import Schema

from accounts.schemas import BoardMemberOut
from core.schemas import InputSchema


class TaskIn(InputSchema):
    """A task as the board writes it: whole, every key required.

    A key left out never erases a value. The values themselves are checked by
    the model, whose messages are in French.
    """

    # The id of an event, or none for a general task.
    event: int | None
    title: str
    # The id of a board member, or none.
    assignee: int | None
    due_date: dt.date | None
    # Done or not: the API records when it was done.
    done: bool


class TaskOut(Schema):
    """A task, with whom it is assigned to and when it was done."""

    id: int
    # The id of its event, or none for a general task.
    event: int | None
    title: str
    assignee: BoardMemberOut | None
    due_date: dt.date | None
    # Done once set.
    done_at: dt.datetime | None
    # None once the account is deleted.
    created_by: BoardMemberOut | None

    @staticmethod
    def resolve_event(task):
        return task.event_id
