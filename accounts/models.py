from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """Manager of a user identified by an email address instead of a username."""

    use_in_migrations = True

    @classmethod
    def normalize_email(cls, email):
        # The email address is the login identifier: stored lower-cased, so that
        # uniqueness and sign-in do not depend on how it was typed.
        return super().normalize_email(email).lower()

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The email address is required.")
        user = self.model(email=self.normalize_email(email), **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def get_by_natural_key(self, username):
        # Signing in, through the API as through the admin, ignores the case of
        # the address typed, which is stored lower-cased.
        return super().get_by_natural_key(self.normalize_email(username))

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields["is_staff"] is not True:
            raise ValueError("A superuser must have is_staff=True.")
        if extra_fields["is_superuser"] is not True:
            raise ValueError("A superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


# Named after their model rather than nested in it: the OpenAPI document names an
# enumeration after its class (see events/models.py).
class BoardPosition(models.TextChoices):
    """The positions of the board (decision of 10/10/2026): a closed list."""

    PRESIDENT = "president", "Président·e"
    VICE_PRESIDENT = "vice_president", "Vice-président·e"
    TREASURER = "treasurer", "Trésorier·e"
    ASSISTANT_TREASURER = "assistant_treasurer", "Trésorier·e adjoint·e"
    SECRETARY = "secretary", "Secrétaire"
    ASSISTANT_SECRETARY = "assistant_secretary", "Secrétaire adjoint·e"


class AccountState(models.TextChoices):
    """Where an account stands, worked out: its invitation awaits a password,
    it signs in, or it is deactivated.
    """

    PENDING = "pending", "Invitation envoyée"
    ACTIVE = "active", "Actif"
    INACTIVE = "inactive", "Désactivé"


class User(AbstractUser):
    """An account, signed in with an email address.

    The board space is reserved to board members (accounts/services/roles.py).
    """

    username = None
    email = models.EmailField(
        _("email address"),
        unique=True,
        error_messages={"unique": "Un compte existe déjà avec cette adresse."},
    )
    position = models.CharField(
        "fonction",
        max_length=100,
        blank=True,
        default="",
        # Also set in the database, so that the previous release, which does not
        # know the column, can still create accounts (see CLAUDE.md).
        db_default="",
        choices=BoardPosition.choices,
        help_text="Affichée dans l'espace bureau. Elle ne donne aucun droit.",
    )
    # When the last link to choose a password went out: an invitation, or a
    # password forgotten (5.9). None while none did.
    link_sent_at = models.DateTimeField("lien envoyé le", null=True, blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()
