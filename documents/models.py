import uuid
from decimal import Decimal
from pathlib import PurePath

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from events.models import Event


# Named after their model rather than nested in it: the OpenAPI document names an
# enumeration after its class (see events/models.py).
class DocumentCategory(models.TextChoices):
    INVOICE = "invoice", "Facture"
    ORDER = "order", "Commande"
    MINUTES = "minutes", "Compte rendu"
    MISC = "misc", "Divers"


class DocumentStatus(models.TextChoices):
    TO_REVIEW = "to_review", "À vérifier"
    VALIDATED = "validated", "Validé"


class DocumentSource(models.TextChoices):
    UPLOAD = "upload", "Dépôt"
    V1_IMPORT = "v1_import", "Import de la v1"


def document_path(document, filename):
    # The name on disk tells nothing of the document: a random UUID, with the
    # extension of the type the server recognised in its content.
    return f"documents/{uuid.uuid4()}{PurePath(filename).suffix}"


class Document(models.Model):
    """A document of the committee: an invoice, an order, the minutes of a meeting
    or any other paper. Stored outside the web root and served to the board alone
    (A8).
    """

    file = models.FileField("fichier", upload_to=document_path)
    # The file as the member sent it: its name, and the type and size of what
    # is stored, a PDF or a WebP (D9).
    original_name = models.CharField("nom d’origine", max_length=255)
    mime_type = models.CharField("type", max_length=50)
    size = models.PositiveBigIntegerField("taille")
    # The fingerprint of the bytes the member sent: the same file twice is the
    # same document.
    sha256 = models.CharField("empreinte", max_length=64)
    category = models.CharField("catégorie", max_length=20, choices=DocumentCategory.choices)
    status = models.CharField(
        "statut", max_length=20, choices=DocumentStatus.choices, default=DocumentStatus.TO_REVIEW
    )
    title = models.CharField("titre", max_length=200)
    document_date = models.DateField("date du document", null=True, blank=True)
    issuer = models.CharField("émetteur", max_length=200, blank=True)
    reference = models.CharField("numéro", max_length=100, blank=True)
    amount = models.DecimalField(
        "montant",
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal(0))],
    )
    due_date = models.DateField("échéance", null=True, blank=True)
    paid_on = models.DateField("payée le", null=True, blank=True)
    # A document outlives its event: an invoice is kept.
    event = models.ForeignKey(
        Event,
        verbose_name="événement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="documents",
        error_messages={"invalid": "Choisissez un événement existant."},
    )
    # What belongs to one kind of document only: the delivery date and the
    # items of an order, the abstract, decisions and tasks of the minutes, the
    # key date of any other paper.
    extracted = models.JSONField("données extraites", default=dict, blank=True)
    note = models.TextField("remarque", blank=True)
    source = models.CharField(
        "source", max_length=20, choices=DocumentSource.choices, default=DocumentSource.UPLOAD
    )
    # A deleted account leaves its documents behind, without a name.
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="déposé par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_documents",
    )
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="validé par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="validated_documents",
    )
    validated_at = models.DateTimeField("validé le", null=True, blank=True)
    created_at = models.DateTimeField("déposé le", auto_now_add=True)

    class Meta:
        verbose_name = "document"
        constraints = [
            # Django locates the error of a single-field unique constraint under
            # its field only when its code is "unique".
            models.UniqueConstraint(
                fields=["sha256"],
                name="document_unique_sha256",
                violation_error_code="unique",
                violation_error_message="Ce fichier a déjà été déposé.",
            ),
            models.CheckConstraint(
                condition=Q(status=DocumentStatus.TO_REVIEW, validated_at__isnull=True)
                | Q(status=DocumentStatus.VALIDATED, validated_at__isnull=False),
                name="document_validated_when_dated",
                violation_error_message="Un document validé porte la date de sa validation.",
            ),
        ]

    def __str__(self):
        return self.title
