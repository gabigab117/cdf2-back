from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower

from events.models import Event

# The longest a loan lasts, both its days counted: beyond, a date was mistyped
# (decision of 10/10/2026).
LOAN_MAX_DAYS = 31


# Named after their model rather than nested in it: the OpenAPI document names an
# enumeration after its class (see events/models.py).
class EquipmentCategory(models.TextChoices):
    FURNITURE = "furniture", "Mobilier"
    MARQUEES = "marquees", "Barnums"
    SOUND_AND_LIGHT = "sound_and_light", "Son et lumière"
    KITCHEN = "kitchen", "Cuisine"
    STREET_AND_GAMES = "street_and_games", "Voirie et jeux"


class LoanBorrowerType(models.TextChoices):
    ASSOCIATION = "association", "Association"
    INDIVIDUAL = "individual", "Particulier"
    MUNICIPALITY = "municipality", "Commune"
    # Not a borrower: the committee keeps the equipment for one of its events (A14).
    COMMITTEE = "committee", "Usage comité"


class LoanStatus(models.TextChoices):
    """The statuses a loan records (A14). « À préparer » and « En retard » are
    states worked out from its dates: see LoanState.
    """

    CONFIRMED = "confirmed", "Confirmé"
    OUT = "out", "Sorti"
    RETURNED = "returned", "Rendu"
    CANCELLED = "cancelled", "Annulé"


class LoanState(models.TextChoices):
    """Where a loan stands today, its pill and its chip: its status, with its
    dates (A14). A committee loan has neither checkout nor return.
    """

    TO_PREPARE = "to_prepare", "À préparer"
    CONFIRMED = "confirmed", "Confirmé"
    OUT = "out", "En cours"
    OVERDUE = "overdue", "En retard"
    COMMITTEE = "committee", "Usage comité"
    RETURNED = "returned", "Rendu"
    CANCELLED = "cancelled", "Annulé"


class Equipment(models.Model):
    """Equipment the committee owns and lends, counted by the piece: folding
    tables, benches, marquees, sound…
    """

    name = models.CharField("nom", max_length=120)
    category = models.CharField("catégorie", max_length=20, choices=EquipmentCategory.choices)
    storage_location = models.CharField("rangement", max_length=120, blank=True)
    # Zero for equipment gone, whose loans keep it in their history: it cannot
    # be deleted.
    total_quantity = models.PositiveIntegerField("quantité totale")
    # Pieces out of use until they are mended: never lent.
    repair_quantity = models.PositiveIntegerField("en réparation", default=0)
    # What replacing one piece would cost: the value of a loan's equipment.
    unit_value = models.DecimalField(
        "valeur de remplacement",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal(0))],
    )
    repair_note = models.TextField("note de réparation", blank=True)

    class Meta:
        verbose_name = "matériel"
        verbose_name_plural = "matériels"
        ordering = ["name", "pk"]
        constraints = [
            # An expression: Django places its error on the form, not on the name.
            models.UniqueConstraint(
                Lower("name"),
                name="equipment_unique_name",
                violation_error_message="Un matériel porte déjà ce nom.",
            ),
            models.CheckConstraint(
                condition=Q(repair_quantity__lte=F("total_quantity")),
                name="equipment_repair_within_total",
                violation_error_message=("La quantité en réparation dépasse la quantité totale."),
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        # The constraint keeps the rule in the database; this places its error
        # under the field the member typed. A quantity missing is the field's
        # own error.
        if self.repair_quantity is None or self.total_quantity is None:
            return
        if self.repair_quantity > self.total_quantity:
            raise ValidationError(
                {"repair_quantity": "La quantité en réparation dépasse la quantité totale."}
            )


class Loan(models.Model):
    """Equipment lent for a few days: to an association, a person, the
    municipality, or kept by the committee for one of its own events (A14).

    The phone of the borrower, and the name of a person, are personal data,
    erased after the return (A9).
    """

    # P-2026-018, given when the loan is recorded, in sequence within its year
    # (A16). NULL, not empty, for a committee loan, which has none: two empty
    # numbers would collide.
    number = models.CharField("numéro", max_length=20, unique=True, null=True, blank=True)
    borrower_type = models.CharField(
        "type d’emprunteur", max_length=20, choices=LoanBorrowerType.choices
    )
    # Empty for a committee loan, which shows the title of its event.
    borrower_name = models.CharField("emprunteur", max_length=200, blank=True)
    purpose = models.CharField("objet", max_length=200, blank=True)
    phone = models.CharField("téléphone", max_length=30, blank=True)
    start_date = models.DateField("sortie")
    end_date = models.DateField("retour")
    status = models.CharField(
        "statut", max_length=20, choices=LoanStatus.choices, default=LoanStatus.CONFIRMED
    )
    # A cheque the board keeps and never cashes, by default after the type of
    # borrower (A16).
    deposit_amount = models.DecimalField(
        "caution",
        max_digits=7,
        decimal_places=2,
        default=Decimal(0),
        validators=[MinValueValidator(Decimal(0))],
    )
    # The event a committee loan keeps its equipment for: deleted with it, like
    # its notes and its stations.
    event = models.ForeignKey(
        Event,
        verbose_name="événement",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="loans",
        error_messages={"invalid": "Choisissez un événement existant."},
    )
    # For the board alone: never printed on the agreement.
    notes = models.TextField("remarques", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="saisi par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="loans",
    )
    created_at = models.DateTimeField("saisi le", auto_now_add=True)
    # When the equipment came back: the purge of personal data counts from it.
    returned_at = models.DateTimeField("rendu le", null=True, blank=True)

    class Meta:
        verbose_name = "prêt"
        ordering = ["-start_date", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=F("start_date")),
                name="loan_ends_after_start",
                violation_error_message="La date de retour est avant la date de sortie.",
            ),
            models.CheckConstraint(
                condition=Q(
                    borrower_type=LoanBorrowerType.COMMITTEE,
                    event__isnull=False,
                    number__isnull=True,
                    borrower_name="",
                    phone="",
                    deposit_amount=0,
                )
                | (
                    ~Q(borrower_type=LoanBorrowerType.COMMITTEE)
                    & Q(event__isnull=True, number__isnull=False)
                    & ~Q(borrower_name="")
                ),
                name="loan_committee_or_borrower",
                violation_error_message=(
                    "Un usage comité réserve pour un événement, sans numéro, emprunteur, "
                    "téléphone ni caution ; un prêt à un tiers a un numéro et un emprunteur."
                ),
            ),
            models.CheckConstraint(
                condition=Q(status=LoanStatus.RETURNED, returned_at__isnull=False)
                | (~Q(status=LoanStatus.RETURNED) & Q(returned_at__isnull=True)),
                name="loan_returned_when_dated",
                violation_error_message="Un prêt rendu porte la date de son retour.",
            ),
            # One reservation per event: a cancelled one leaves room for another.
            # Django places the error of a single-field constraint under its
            # field only when its code is "unique".
            models.UniqueConstraint(
                fields=["event"],
                condition=~Q(status=LoanStatus.CANCELLED),
                name="loan_unique_committee_event",
                violation_error_code="unique",
                violation_error_message="Cet événement a déjà sa réservation de matériel.",
            ),
        ]

    def __str__(self):
        return self.number or self.display_name

    @property
    def display_name(self):
        """Who the loan is for: its borrower, or the event a committee loan keeps
        its equipment for.
        """
        return self.event.title if self.event_id else self.borrower_name

    def clean(self):
        # The constraints keep these rules in the database; this places their
        # errors under the fields the member typed.
        errors = {}
        if self.borrower_type == LoanBorrowerType.COMMITTEE:
            if self.event_id is None:
                errors["event"] = "Choisissez l’événement du comité."
        elif not self.borrower_name:
            errors["borrower_name"] = self._meta.get_field("borrower_name").error_messages["blank"]
        # A date missing is the field's own error.
        if self.start_date is not None and self.end_date is not None:
            days = (self.end_date - self.start_date).days + 1
            if days < 1:
                errors["end_date"] = "La date de retour est avant la date de sortie."
            elif days > LOAN_MAX_DAYS:
                errors["end_date"] = f"Un prêt dure au plus {LOAN_MAX_DAYS} jours."
        if errors:
            raise ValidationError(errors)


class LoanLine(models.Model):
    """The pieces of one equipment a loan takes, and how they came back."""

    loan = models.ForeignKey(
        Loan, verbose_name="prêt", on_delete=models.CASCADE, related_name="lines"
    )
    # Equipment that was lent is never deleted: its loans keep their history,
    # which the v1 erased.
    equipment = models.ForeignKey(
        Equipment,
        verbose_name="matériel",
        on_delete=models.PROTECT,
        related_name="loan_lines",
        error_messages={"invalid": "Choisissez un matériel existant."},
    )
    # The validator places its error under the field; the constraint keeps the
    # rule in the database.
    quantity = models.PositiveIntegerField("quantité", validators=[MinValueValidator(1)])
    # Counted at the return (A17): the damaged pieces go under repair, the
    # missing ones are reported, the stock left as it is.
    damaged_quantity = models.PositiveIntegerField("abîmées", default=0)
    missing_quantity = models.PositiveIntegerField("manquantes", default=0)

    class Meta:
        verbose_name = "ligne de prêt"
        verbose_name_plural = "lignes de prêt"
        ordering = ["equipment__name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "equipment"],
                name="loan_line_unique_equipment",
                violation_error_message="Ce matériel figure déjà dans le prêt.",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=1),
                name="loan_line_some_pieces",
                violation_error_message="Indiquez au moins une pièce.",
            ),
            models.CheckConstraint(
                condition=Q(quantity__gte=F("damaged_quantity") + F("missing_quantity")),
                name="loan_line_return_within_quantity",
                violation_error_message=(
                    "Les pièces abîmées et manquantes dépassent la quantité prêtée."
                ),
            ),
        ]

    def __str__(self):
        return f"{self.equipment} : {self.quantity}"


class LoanNumberSequence(models.Model):
    """The last number a loan received in a year: P-2026-018 follows P-2026-017
    (A16). Its row is locked while a loan is numbered, so that two loans
    recorded at once never take the same number.
    """

    year = models.PositiveSmallIntegerField("année", primary_key=True)
    last_number = models.PositiveIntegerField("dernier numéro", default=0)

    class Meta:
        verbose_name = "compteur des numéros de prêt"
        verbose_name_plural = "compteurs des numéros de prêt"

    def __str__(self):
        return f"{self.year} : {self.last_number}"
