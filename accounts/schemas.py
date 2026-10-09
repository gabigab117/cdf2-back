from typing import Annotated

from ninja import Schema
from pydantic import StringConstraints

from core.schemas import InputSchema


class LoginIn(InputSchema):
    # A plain string: a malformed address fails like any wrong credential.
    email: str
    # Checked exactly as typed: Django never alters a password either.
    password: Annotated[str, StringConstraints(strip_whitespace=False)]


class AccessTokenOut(Schema):
    access: str


# A plain Schema rather than a ModelSchema, which would publish the fields that
# may be blank as optional and nullable.
class MeOut(Schema):
    email: str
    first_name: str
    last_name: str
    position: str


class BoardMemberOut(Schema):
    """A board member as the board space names them, the lead of an event.

    An account created without a name, such as with createsuperuser, is named
    after its email address.
    """

    id: int
    first_name: str
    last_name: str
    email: str
