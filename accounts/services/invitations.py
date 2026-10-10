"""The accounts of the board (5.9, D8): the superuser invites a member, who
chooses their password from a link; the same gesture sends a new link to a
member who forgot theirs.

No invitation is stored. The link carries Django's own password reset token,
which holds a print of the password and of the last sign-in: it serves once,
for PASSWORD_RESET_TIMEOUT.
"""

import logging
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth.hashers import UNUSABLE_PASSWORD_PREFIX
from django.contrib.auth.models import Group
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Case, CharField, QuerySet, Value, When
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from accounts.models import AccountState, User
from accounts.schemas import AccountIn, PasswordIn, PasswordLinkIn
from accounts.services.roles import BOARD_GROUP
from core.services.mail import MAIL_FAILURES
from core.text import counted

logger = logging.getLogger(__name__)

# The pages of the front end the email leads to. The link's token follows the
# "#", which a browser never sends to a server: it stays out of nginx's log
# and of any Referer.
PASSWORD_PAGE = "/choisir-mot-de-passe"
SIGN_IN_PAGE = "/connexion"

INVALID_LINK = (
    "Ce lien n’est plus valable. Demandez-en un nouveau à la personne qui gère "
    "les comptes du bureau."
)

DAY = 24 * 60 * 60


@dataclass(frozen=True)
class Invitation:
    """An account, and whether the email of its link went out."""

    account: User
    sent: bool


def accounts() -> QuerySet[User]:
    """The accounts with their state, by name: an inactive account is
    deactivated, one without a usable password awaits its password.
    """
    state = Case(
        When(is_active=False, then=Value(AccountState.INACTIVE)),
        When(
            password__startswith=UNUSABLE_PASSWORD_PREFIX,
            then=Value(AccountState.PENDING_INVITATION),
        ),
        default=Value(AccountState.ACTIVE),
        output_field=CharField(),
    )
    return User.objects.annotate(state=state).order_by("first_name", "last_name", "email")


def invite(data: AccountIn) -> Invitation:
    """Make the account of a board member, then send them their link.

    The account is active, in the board group, neither staff nor superuser:
    the admin stays the superuser's. Its password is unusable, so that it
    cannot sign in before its member chooses one. A failure to send leaves the
    account made, and is told.
    """
    with transaction.atomic():
        account = User(
            email=User.objects.normalize_email(data.email),
            first_name=data.first_name,
            last_name=data.last_name,
            position=data.position or "",
        )
        account.set_unusable_password()
        _check(account)
        account.save()
        account.groups.add(Group.objects.get(name=BOARD_GROUP))
    return new_link(account)


def new_link(account: User) -> Invitation:
    """« Envoyer un nouveau lien »: an invitation again while the account
    awaits its password; else, a password forgotten, the former working until
    another is chosen. An earlier link holds until it expires, and the first
    used spends the others.
    """
    if not account.is_active:
        raise ValidationError("Ce compte est désactivé : il ne reçoit plus de lien.")
    message = mail.EmailMessage(_subject(account), _body(account), to=[account.email])
    try:
        mail.mailers.default.send_messages([message])
    except MAIL_FAILURES:
        logger.exception("The link of account %s could not be sent.", account.pk)
        sent = False
    else:
        account.link_sent_at = timezone.now()
        account.save(update_fields=["link_sent_at"])
        sent = True
    return Invitation(accounts().get(pk=account.pk), sent)


def link_account(data: PasswordLinkIn) -> User:
    """The active account a link leads to, while it holds."""
    return _linked(User.objects.all(), data)


@transaction.atomic
def set_password(data: PasswordIn) -> User:
    """Record the password a member chose from their link, which then holds no
    more. Django's validators judge it with the account, so that it may not be
    too close to its names or address.
    """
    # Read again under a lock, then checked: of two sendings of the same link,
    # the second finds its token spent.
    account = _linked(User.objects.select_for_update(), data)
    errors: dict[str, list[str]] = {}
    try:
        validate_password(data.password, user=account)
    except ValidationError as error:
        errors["password"] = error.messages
    if data.confirmation != data.password:
        errors["confirmation"] = ["Les deux mots de passe ne correspondent pas."]
    if errors:
        raise ValidationError(errors)
    account.set_password(data.password)
    account.save(update_fields=["password"])
    return account


def _check(account: User) -> None:
    """Validate an account as Django does, every error at once. An invited
    member is named, unlike an account made otherwise, such as by
    createsuperuser.
    """
    errors: dict[str, list[str]] = {
        field: [User._meta.get_field(field).error_messages["blank"]]
        for field in ("first_name", "last_name")
        if not getattr(account, field)
    }
    try:
        account.full_clean()
    except ValidationError as error:
        for field, messages in error.message_dict.items():
            errors.setdefault(field, []).extend(messages)
    if errors:
        raise ValidationError(errors)


def _linked(users: QuerySet[User], data: PasswordLinkIn) -> User:
    # As Django's own PasswordResetConfirmView reads a link: a malformed one
    # is refused like an expired one.
    try:
        pk = User._meta.pk.to_python(urlsafe_base64_decode(data.uid).decode())
        account = users.get(pk=pk, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist, ValidationError):
        raise ValidationError(INVALID_LINK) from None
    if not default_token_generator.check_token(account, data.token):
        raise ValidationError(INVALID_LINK)
    return account


def _subject(account: User) -> str:
    if account.has_usable_password():
        return "Nouveau mot de passe pour l’espace du bureau du Comité des fêtes"
    return "Votre accès à l’espace du bureau du Comité des fêtes"


def _body(account: User) -> str:
    uid = urlsafe_base64_encode(force_bytes(account.pk))
    token = default_token_generator.make_token(account)
    days = counted(settings.PASSWORD_RESET_TIMEOUT // DAY, "jour", "jours")
    greeting = f"Bonjour {account.first_name}," if account.first_name else "Bonjour,"
    if account.has_usable_password():
        purpose = (
            "Voici un lien pour choisir un nouveau mot de passe pour l’espace du bureau du "
            "Comité des fêtes. Votre mot de passe actuel reste valable tant que vous n’en "
            "avez pas choisi un autre."
        )
    else:
        purpose = (
            "Un compte vous attend dans l’espace du bureau du Comité des fêtes. Choisissez "
            "votre mot de passe pour y entrer."
        )
    return (
        f"{greeting}\n"
        f"\n"
        f"{purpose}\n"
        f"\n"
        f"Ce lien est valable {days} :\n"
        f"{settings.SITE_URL}{PASSWORD_PAGE}#{uid}.{token}\n"
        f"\n"
        f"Ensuite, connectez-vous depuis cette page :\n"
        f"{settings.SITE_URL}{SIGN_IN_PAGE}\n"
    )
