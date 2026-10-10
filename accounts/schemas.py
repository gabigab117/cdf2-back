import datetime as dt
from typing import Annotated

from ninja import Schema
from pydantic import StringConstraints

from accounts.models import AccountState, BoardPosition
from core.schemas import InputSchema

# A password is checked exactly as typed: Django never alters one either.
Password = Annotated[str, StringConstraints(strip_whitespace=False)]


class LoginIn(InputSchema):
    # A plain string: a malformed address fails like any wrong credential.
    email: str
    password: Password


class AccessTokenOut(Schema):
    access: str


# A plain Schema rather than a ModelSchema, which would publish the fields that
# may be blank as optional and nullable.
class MeOut(Schema):
    email: str
    first_name: str
    last_name: str
    # The label of the position, as the board space shows it: "" for none.
    position: str
    # The accounts page is the superuser's alone: the front end shows its entry.
    is_superuser: bool

    @staticmethod
    def resolve_position(account):
        return account.get_position_display()


class BoardMemberOut(Schema):
    """A board member as the board space names them, the lead of an event.

    An account created without a name, such as with createsuperuser, is named
    after its email address.
    """

    id: int
    first_name: str
    last_name: str
    email: str


class AccountIn(InputSchema):
    """The account of a board member the superuser invites."""

    # Checked by the account's own field, as Django words it.
    email: str
    first_name: str
    last_name: str
    # None: no position.
    position: BoardPosition | None = None


class AccountOut(Schema):
    """An account, as the accounts page lists it."""

    id: int
    email: str
    first_name: str
    last_name: str
    # The label of the position: "" for none.
    position: str
    state: AccountState
    is_superuser: bool
    # When the last link went out: None while none did.
    link_sent_at: dt.datetime | None

    @staticmethod
    def resolve_position(account):
        return account.get_position_display()


class InvitationOut(Schema):
    """An account, and whether the email of its link went out."""

    account: AccountOut
    sent: bool


class PasswordLinkIn(InputSchema):
    """The link a member received, as the page read it after its "#"."""

    uid: str
    token: str


class PasswordIn(PasswordLinkIn):
    """The password a member chooses from their link, typed twice."""

    password: Password
    confirmation: Password


class PasswordLinkOut(Schema):
    """The account a link leads to, by its email address."""

    email: str
