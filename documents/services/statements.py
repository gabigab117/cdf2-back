"""The sworn statement of a purchase whose receipt was lost (D14).

The member who paid types what the receipt would have told. The application
writes it as their statement, on their honour, in a PDF it files among the
documents as an invoice: paid on the day of the purchase, it awaits review like
a deposit. It is no invoice in the supplier's name, which would be a forgery:
the supplier heads the page in plain text, above the committee's statement.

The PDF holds what was attested. Correcting the document changes its fields,
never its file: another statement replaces it.

The PDF is drawn by ReportLab, the library Django's documentation uses. It is
not thread-safe: the API's workers are synchronous, without threads.
"""

import datetime as dt
import hashlib
from decimal import Decimal
from io import BytesIO
from xml.sax.saxutils import escape

from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.core.files.base import ContentFile
from django.template.defaultfilters import floatformat
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table

from accounts.models import User
from core.text import COMMITTEE
from documents.models import Document, DocumentCategory, DocumentSource
from documents.schemas import SwornStatementIn
from documents.services.documents import record_document
from documents.services.files import PDF, StoredFile

NO_AMOUNT = "Indiquez un montant supérieur à zéro."
FUTURE_PURCHASE = "La date de l’achat ne peut pas être dans le futur."
UNNAMED = (
    "Une attestation porte le prénom et le nom de la personne qui la fait : "
    "l’administrateur des comptes doit d’abord les ajouter à votre compte."
)

# The fields of the statement, as the document stores them: an error of the
# model is told on the field the member typed.
FIELDS = {"issuer": "supplier", "document_date": "purchase_date", "title": "purchase"}
# The file is made once the statement is checked.
FILE_FIELDS = {"file", "original_name", "mime_type", "size", "sha256"}

# A document without an event, as the board calls it.
NO_EVENT = "Fonctionnement du comité"

# Helvetica, one of the fonts every PDF reader holds: nothing to embed. It
# writes the characters of Windows-1252, the French ones and « € » among them.
REGULAR = "Helvetica"
BOLD = "Helvetica-Bold"
# The colours of the board space: its text, its secondary text, its rules.
INK = colors.HexColor("#0C0E13")
MUTED = colors.HexColor("#5B6272")
RULE = colors.HexColor("#C3C8D2")

SUPPLIER = ParagraphStyle("supplier", fontName=BOLD, fontSize=26, leading=31, textColor=INK)
PURCHASED = ParagraphStyle("purchased", fontName=REGULAR, fontSize=11, leading=15, textColor=MUTED)
TITLE = ParagraphStyle("title", fontName=BOLD, fontSize=15, leading=19, textColor=INK)
SUBTITLE = ParagraphStyle("subtitle", fontName=REGULAR, fontSize=10, leading=14, textColor=MUTED)
BODY = ParagraphStyle("body", fontName=REGULAR, fontSize=11, leading=16, textColor=INK)
LABEL = ParagraphStyle("label", fontName=REGULAR, fontSize=10, leading=15, textColor=MUTED)
VALUE = ParagraphStyle("value", fontName=BOLD, fontSize=11, leading=15, textColor=INK)

MARGIN = 20 * mm
LABEL_WIDTH = 42 * mm


def create_sworn_statement(data: SwornStatementIn, member: User) -> Document:
    """Attest a purchase on the honour of the member who paid it: its PDF is
    filed as an invoice paid on the day of the purchase, which awaits review.
    """
    made_at = timezone.localtime()
    document = Document(
        category=DocumentCategory.INVOICE,
        source=DocumentSource.SWORN_STATEMENT,
        title=data.purchase,
        issuer=data.supplier,
        document_date=data.purchase_date,
        # A till receipt is paid on the spot: the invoice is paid (A18).
        paid_on=data.purchase_date,
        amount=data.amount,
        event_id=data.event,
        uploaded_by=member,
    )
    _check(document, member, made_at.date())
    content = statement_pdf(document, member, made_at)
    stored = StoredFile(
        ContentFile(content),
        f"Attestation — {document.issuer} — {document.document_date:%d-%m-%Y}.pdf",
        PDF,
        len(content),
        hashlib.sha256(content).hexdigest(),
    )
    document.original_name = stored.name
    document.mime_type = stored.mime_type
    document.size = stored.size
    document.sha256 = stored.sha256
    return record_document(document, stored)


def statement_pdf(document: Document, member: User, made_at: dt.datetime) -> bytes:
    """The statement of a purchase, on one A4 page: the supplier at its head,
    then what the member attests, and when they did.
    """
    name = escape(member.get_full_name())
    buffer = BytesIO()
    page = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
        title=f"Attestation de dépense sur l’honneur — {document.issuer}",
        author=member.get_full_name(),
        subject=f"Achat du {document.document_date:%d/%m/%Y} : {document.title}",
        creator=COMMITTEE,
        lang="fr-FR",
    )
    page.build(
        [
            Paragraph(escape(document.issuer), SUPPLIER),
            Spacer(0, 2 * mm),
            Paragraph(f"Achat du {document.document_date:%d/%m/%Y}", PURCHASED),
            HRFlowable(
                width="100%", thickness=0.8, color=RULE, spaceBefore=8 * mm, spaceAfter=8 * mm
            ),
            Paragraph("Attestation de dépense sur l’honneur", TITLE),
            Spacer(0, 1 * mm),
            Paragraph(COMMITTEE, SUBTITLE),
            Spacer(0, 9 * mm),
            Paragraph(
                f"Je soussigné·e {name}, {_role(member)} du {COMMITTEE}, atteste sur "
                "l’honneur avoir payé l’achat suivant pour le compte du comité :",
                BODY,
            ),
            Spacer(0, 5 * mm),
            _details(document),
            Spacer(0, 7 * mm),
            Paragraph(
                "Le ticket de caisse de cet achat a été perdu : cette attestation le remplace "
                "comme justificatif.",
                BODY,
            ),
            Spacer(0, 12 * mm),
            Paragraph(
                f"Fait le {made_at:%d/%m/%Y} à {made_at:%H} h {made_at:%M}, depuis l’espace "
                f"du bureau, par {name}.",
                BODY,
            ),
        ]
    )
    return buffer.getvalue()


def _role(member: User) -> str:
    # « trésorier·e », within a sentence; a member without a position is one
    # of the board.
    return member.get_position_display().lower() or "membre du bureau"


def _details(document: Document) -> Table:
    event = document.event.title if document.event else NO_EVENT
    rows = [
        ("Fournisseur", document.issuer),
        ("Date de l’achat", f"{document.document_date:%d/%m/%Y}"),
        ("Achat", document.title),
        ("Montant TTC", _euros(document.amount)),
        ("Événement", event),
    ]
    return Table(
        [[Paragraph(label, LABEL), Paragraph(escape(value), VALUE)] for label, value in rows],
        # The values take the rest of the frame's width.
        colWidths=[LABEL_WIDTH, "*"],
        style=[
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, -2), 0.5, RULE),
        ],
    )


def _euros(amount: Decimal) -> str:
    # « 1 234,50 € », as Django writes a number in French: its floatformat
    # filter, grouped (« g »), with a non-breaking space between thousands.
    return f"{floatformat(amount, '2g')}\xa0€"


def _check(document: Document, member: User, today: dt.date) -> None:
    """Validate a statement as Django does, every error at once. It names a
    supplier, a purchase of the past and an amount above zero, and the member
    who makes it.
    """
    errors: dict[str, list[str]] = {}
    if not document.issuer:
        errors["supplier"] = [Document._meta.get_field("issuer").error_messages["blank"]]
    # Django's MinValueValidator would write its limit unlocalised (« 0.01 »),
    # and a MaxValueValidator of today the date in the ISO format.
    if document.amount <= 0:
        errors["amount"] = [NO_AMOUNT]
    if document.document_date > today:
        errors["purchase_date"] = [FUTURE_PURCHASE]
    if not (member.first_name and member.last_name):
        errors[NON_FIELD_ERRORS] = [UNNAMED]
    try:
        document.full_clean(exclude=FILE_FIELDS)
    except ValidationError as error:
        for field, messages in error.message_dict.items():
            # A field already refused keeps the statement's own message.
            errors.setdefault(FIELDS.get(field, field), messages)
    if errors:
        raise ValidationError(errors)
