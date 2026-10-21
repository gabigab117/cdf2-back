"""The committee's ledger (A18): a single record of income and expenses, each
entry tied to an event or to the committee's general running. There is no bank
balance.
"""

from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from accounts.services.roles import BOARD_MEMBERS
from documents.models import Document
from events.models import EVENT_ERROR_MESSAGES, Event

NOT_IN_FUTURE = "La date ne peut pas être dans le futur."
NO_AMOUNT = "Indiquez un montant supérieur à zéro."
# Rules a constraint keeps in the database, and clean() places under their field.
INCOME_NOT_ADVANCED = "Une recette n’est pas avancée par un membre."
ADVANCE_ALONE_NAMES_MEMBER = "Seule une avance nomme le membre qui l’a faite."
REIMBURSED_BEFORE_ADVANCE = "Le remboursement ne peut pas précéder l’avance."
STOCK_PURCHASE_OF_EXPENSE = "Seule une dépense paie un achat du stock."
PAID_BY_ANOTHER = "Cet achat est déjà payé par une autre dépense."


# Named after their model rather than nested in it: the OpenAPI document names an
# enumeration after its class (see events/models.py).
class LedgerEntryKind(models.TextChoices):
    INCOME = "income", "Recette"
    EXPENSE = "expense", "Dépense"


class LedgerCategory(models.TextChoices):
    """What an entry is for: each kind has its own categories, « Divers » both."""

    FOOD = "food", "Achats alimentaires"
    DRINKS = "drinks", "Boissons"
    EQUIPMENT_RENTAL = "equipment_rental", "Location de matériel"
    DECORATION = "decoration", "Décoration"
    PRIZES = "prizes", "Lots et cadeaux"
    INSURANCE = "insurance", "Assurance"
    BANK_FEES = "bank_fees", "Frais bancaires"
    BAR = "bar", "Buvette"
    PITCHES = "pitches", "Emplacements"
    TICKETS = "tickets", "Entrées et tickets"
    GRANT = "grant", "Subvention"
    MEMBERSHIP_FEES = "membership_fees", "Cotisations"
    DONATIONS = "donations", "Dons"
    MISC = "misc", "Divers"


# The categories of each kind, in the order of the form.
EXPENSE_CATEGORIES = (
    LedgerCategory.FOOD,
    LedgerCategory.DRINKS,
    LedgerCategory.EQUIPMENT_RENTAL,
    LedgerCategory.DECORATION,
    LedgerCategory.PRIZES,
    LedgerCategory.INSURANCE,
    LedgerCategory.BANK_FEES,
    LedgerCategory.MISC,
)
INCOME_CATEGORIES = (
    LedgerCategory.BAR,
    LedgerCategory.PITCHES,
    LedgerCategory.TICKETS,
    LedgerCategory.GRANT,
    LedgerCategory.MEMBERSHIP_FEES,
    LedgerCategory.DONATIONS,
    LedgerCategory.MISC,
)
CATEGORIES = {
    LedgerEntryKind.EXPENSE: EXPENSE_CATEGORIES,
    LedgerEntryKind.INCOME: INCOME_CATEGORIES,
}


class LedgerPaymentMethod(models.TextChoices):
    ASSOCIATION_CARD = "association_card", "Carte de l’association"
    CASH = "cash", "Espèces"
    CHEQUE = "cheque", "Chèque"
    TRANSFER = "transfer", "Virement"
    DIRECT_DEBIT = "direct_debit", "Prélèvement"
    # A member paid an expense with their own money: the committee owes it back.
    ADVANCE = "advance", "Avancé par un membre"


class LedgerReceiptState(models.TextChoices):
    """Where the receipt of an entry stands, worked out (6.2): an expense needs
    one, but for its bank fees; an income needs none.
    """

    ATTACHED = "attached", "Joint"
    MISSING = "missing", "Manquant"
    NOT_REQUIRED = "not_required", "Sans objet"


class ReimbursementMethod(models.TextChoices):
    """How the committee paid an advance back to its member."""

    CASH = "cash", "Espèces"
    CHEQUE = "cheque", "Chèque"
    TRANSFER = "transfer", "Virement"


class LedgerEntry(models.Model):
    """A sum of money in or out of the committee, at the date it moved (A18).

    Its amount is always positive: its kind tells income from expense.
    """

    date = models.DateField(
        "date", validators=[MaxValueValidator(timezone.localdate, message=NOT_IN_FUTURE)]
    )
    kind = models.CharField("type", max_length=10, choices=LedgerEntryKind.choices)
    label = models.CharField("libellé", max_length=200)
    # The validator places its error under the field; the constraint keeps the
    # rule in the database.
    amount = models.DecimalField(
        "montant",
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"), message=NO_AMOUNT)],
    )
    category = models.CharField("catégorie", max_length=20, choices=LedgerCategory.choices)
    payment_method = models.CharField(
        "moyen de paiement", max_length=20, choices=LedgerPaymentMethod.choices
    )
    # The member who paid an advance. A deleted account leaves its advances
    # behind without a name: the database only requires that a member be named
    # by an advance, the service that an advance name one when it is written.
    advanced_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="avancé par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advances",
        limit_choices_to=BOARD_MEMBERS,
        error_messages={"invalid": "Choisissez un membre du bureau."},
    )
    # When and how the committee paid an advance back: the advance itself is
    # completed, and no second expense is written (A18).
    reimbursed_on = models.DateField(
        "remboursée le",
        null=True,
        blank=True,
        validators=[MaxValueValidator(timezone.localdate, message=NOT_IN_FUTURE)],
    )
    # NULL rather than empty while unpaid: "" is not a method of the enumeration,
    # and would fail the response.
    reimbursement_method = models.CharField(  # noqa: DJ001
        "moyen de remboursement",
        max_length=10,
        choices=ReimbursementMethod.choices,
        null=True,
        blank=True,
    )
    # None: the committee's general running. The accounts of an event never go
    # without a word: an event that has entries is not deleted.
    event = models.ForeignKey(
        Event,
        verbose_name="événement",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entries",
        error_messages=EVENT_ERROR_MESSAGES,
    )
    # The document that proves the entry. A document proves a single entry; it
    # stays among the documents when the entry is deleted.
    receipt = models.OneToOneField(
        Document,
        verbose_name="justificatif",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entry",
        error_messages={"unique": "Ce document justifie déjà une autre ligne."},
    )
    # The purchase or the delivery of the stock this expense paid (D16): its
    # costs are the share of the expense gone into stock. An operation is paid
    # by a single expense; one an expense paid is not cancelled.
    stock_purchase = models.OneToOneField(
        "stock.StockOperation",
        verbose_name="achat du stock",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="ledger_entry",
        error_messages={"unique": PAID_BY_ANOTHER},
    )
    supplier = models.CharField("fournisseur", max_length=200, blank=True)
    note = models.TextField("note", blank=True)
    # A deleted account leaves its entries behind, without a name.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="saisie par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    created_at = models.DateTimeField("saisie le", auto_now_add=True)

    class Meta:
        verbose_name = "ligne de trésorerie"
        verbose_name_plural = "lignes de trésorerie"
        ordering = ["-date", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(amount__gt=0),
                name="ledger_entry_amount_positive",
                violation_error_message=NO_AMOUNT,
            ),
            models.CheckConstraint(
                condition=Q(kind=LedgerEntryKind.EXPENSE, category__in=EXPENSE_CATEGORIES)
                | Q(kind=LedgerEntryKind.INCOME, category__in=INCOME_CATEGORIES),
                name="ledger_entry_category_of_kind",
                violation_error_message="La catégorie ne correspond pas au type de la ligne.",
            ),
            models.CheckConstraint(
                condition=~Q(payment_method=LedgerPaymentMethod.ADVANCE)
                | Q(kind=LedgerEntryKind.EXPENSE),
                name="ledger_entry_advance_of_expense",
                violation_error_message=INCOME_NOT_ADVANCED,
            ),
            models.CheckConstraint(
                condition=Q(payment_method=LedgerPaymentMethod.ADVANCE)
                | Q(advanced_by__isnull=True),
                name="ledger_entry_member_of_advance",
                violation_error_message=ADVANCE_ALONE_NAMES_MEMBER,
            ),
            models.CheckConstraint(
                condition=Q(reimbursed_on__isnull=True, reimbursement_method__isnull=True)
                | Q(
                    payment_method=LedgerPaymentMethod.ADVANCE,
                    reimbursed_on__isnull=False,
                    reimbursement_method__isnull=False,
                ),
                name="ledger_entry_reimbursed_advance",
                violation_error_message=(
                    "Seule une avance se rembourse, à une date et par un moyen donnés."
                ),
            ),
            models.CheckConstraint(
                condition=Q(reimbursed_on__isnull=True) | Q(reimbursed_on__gte=F("date")),
                name="ledger_entry_reimbursed_after_advance",
                violation_error_message=REIMBURSED_BEFORE_ADVANCE,
            ),
            models.CheckConstraint(
                condition=Q(stock_purchase__isnull=True) | Q(kind=LedgerEntryKind.EXPENSE),
                name="ledger_entry_stock_purchase_of_expense",
                violation_error_message=STOCK_PURCHASE_OF_EXPENSE,
            ),
        ]

    def __str__(self):
        return self.label

    @property
    def contact(self):
        """The member to ask for the receipt: who advanced the expense, or else
        who recorded it.
        """
        return self.advanced_by or self.created_by

    def clean(self):
        # The constraints keep these rules in the database; this places their
        # errors under the fields the member typed. A value missing or out of
        # its choices is the field's own error.
        errors = {}
        categories = CATEGORIES.get(self.kind)
        if categories and self.category and self.category not in categories:
            kind = LedgerEntryKind(self.kind).label.lower()
            errors["category"] = f"Choisissez une catégorie de {kind}."
        advance = self.payment_method == LedgerPaymentMethod.ADVANCE
        reimbursed = self.reimbursed_on is not None or self.reimbursement_method is not None
        if advance and self.kind == LedgerEntryKind.INCOME:
            errors["payment_method"] = INCOME_NOT_ADVANCED
        elif not advance and reimbursed:
            errors["payment_method"] = (
                "Une avance remboursée reste une avance : annulez d’abord son remboursement."
            )
        if not advance and self.advanced_by_id is not None:
            errors["advanced_by"] = ADVANCE_ALONE_NAMES_MEMBER
        if (
            self.reimbursed_on is not None
            and self.date is not None
            and self.reimbursed_on < self.date
        ):
            errors["reimbursed_on"] = REIMBURSED_BEFORE_ADVANCE
        if self.stock_purchase_id is not None and self.kind == LedgerEntryKind.INCOME:
            errors["kind"] = STOCK_PURCHASE_OF_EXPENSE
        if errors:
            raise ValidationError(errors)
