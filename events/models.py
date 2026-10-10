from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q

from accounts.services.roles import BOARD_MEMBERS


# The choices are named after their model rather than nested in it: the OpenAPI
# document names an enumeration after its class, and two of the same name would
# silently replace one another.
class EventCategory(models.TextChoices):
    CHILDREN = "children", "Enfants"
    MEALS = "meals", "Repas"
    MARKETS = "markets", "Marchés"
    GAMES = "games", "Jeux"
    FESTIVITIES = "festivities", "Fêtes"


class PracticalInfoIcon(models.TextChoices):
    PEOPLE = "people", "Personnes"
    HOME = "home", "Maison"
    CHECK = "check", "Coche"
    INFO = "info", "Information"
    WARNING = "warning", "Attention"
    PARKING = "parking", "Stationnement"
    FOOD = "food", "Restauration"
    ACCESSIBILITY = "accessibility", "Accessibilité"


class Event(models.Model):
    """An event of the committee, with the content of its public page."""

    title = models.CharField("titre", max_length=120)
    # The address of the public page. Its unique constraint, below, indexes it
    # already.
    slug = models.SlugField("adresse", max_length=140, db_index=False)
    category = models.CharField("catégorie", max_length=20, choices=EventCategory.choices)
    starts_at = models.DateTimeField("début")
    ends_at = models.DateTimeField("fin", null=True, blank=True)
    start_label = models.CharField(
        "libellé du début", max_length=40, blank=True, help_text="Par exemple « Ouverture »."
    )
    venue_name = models.CharField("lieu", max_length=120)
    venue_address = models.CharField("adresse du lieu", max_length=200, blank=True)
    # A position on the map, in degrees: floats, as no amount is involved.
    latitude = models.FloatField(
        "latitude",
        null=True,
        blank=True,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
    )
    longitude = models.FloatField(
        "longitude",
        null=True,
        blank=True,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
    )
    price_label = models.CharField("tarif", max_length=60, blank=True)
    price_detail = models.CharField("précision sur le tarif", max_length=200, blank=True)
    summary = models.TextField("chapeau", blank=True)
    published = models.BooleanField("publié", default=False)
    lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="responsable",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="led_events",
        limit_choices_to=BOARD_MEMBERS,
        error_messages={"invalid": "Choisissez un membre du bureau."},
    )
    previous_edition = models.ForeignKey(
        "self",
        verbose_name="édition précédente",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="next_editions",
        error_messages={"invalid": "Choisissez un événement existant."},
    )
    # How many places its reservations may take, or none for no limit. It is
    # set from the reservations' tab (D1), never with the rest of the event.
    capacity = models.PositiveIntegerField(
        "capacité", null=True, blank=True, validators=[MinValueValidator(1)]
    )
    updated_at = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        verbose_name = "événement"
        constraints = [
            # Django locates the error of a single-field unique constraint under
            # its field only when its code is "unique".
            models.UniqueConstraint(
                fields=["slug"],
                name="event_unique_slug",
                violation_error_code="unique",
                violation_error_message="Un autre événement utilise déjà cette adresse.",
            ),
            models.CheckConstraint(
                condition=Q(ends_at__isnull=True) | Q(ends_at__gte=F("starts_at")),
                name="event_ends_after_it_starts",
                violation_error_message="La fin de l’événement ne peut pas précéder son début.",
            ),
            models.CheckConstraint(
                condition=Q(latitude__isnull=True, longitude__isnull=True)
                | Q(latitude__isnull=False, longitude__isnull=False),
                name="event_complete_coordinates",
                violation_error_message="Indiquez la latitude et la longitude, ou aucune des deux.",
            ),
            models.CheckConstraint(
                condition=~Q(previous_edition=F("pk")),
                name="event_not_its_own_previous_edition",
                violation_error_message=(
                    "Un événement ne peut pas être sa propre édition précédente."
                ),
            ),
        ]

    def __str__(self):
        return self.title


class ProgrammeItem(models.Model):
    """A line of an event's programme: a time, a title and a description."""

    event = models.ForeignKey(
        Event, verbose_name="événement", on_delete=models.CASCADE, related_name="programme"
    )
    time = models.TimeField("heure")
    title = models.CharField("titre", max_length=120)
    description = models.TextField("description", blank=True)
    # The position in the list the board wrote, which replaces the whole list
    # with bulk_create: Meta.order_with_respect_to would leave its _order unset.
    sort_order = models.PositiveSmallIntegerField("ordre d’affichage")

    class Meta:
        verbose_name = "ligne de programme"
        verbose_name_plural = "lignes de programme"
        ordering = ["sort_order"]

    def __str__(self):
        return f"{self.time:%H:%M} {self.title}"


class PracticalInfo(models.Model):
    """A « Bon à savoir » card of an event: an icon, a title and a text."""

    event = models.ForeignKey(
        Event, verbose_name="événement", on_delete=models.CASCADE, related_name="practical_infos"
    )
    icon = models.CharField("icône", max_length=20, choices=PracticalInfoIcon.choices)
    title = models.CharField("titre", max_length=120)
    text = models.TextField("texte", blank=True)
    # See ProgrammeItem.sort_order.
    sort_order = models.PositiveSmallIntegerField("ordre d’affichage")

    class Meta:
        verbose_name = "« Bon à savoir »"
        verbose_name_plural = "« Bon à savoir »"
        ordering = ["sort_order"]

    def __str__(self):
        return self.title
