"""The only email of the documents (D7): a document deposited is told to the
accounts the superuser chose.

The superuser puts them in the « Notifications documents » group, from the
Django admin: no member subscribes or unsubscribes, and no preference is
stored. The email names the document and leads to it; it holds neither the
file nor its content, which the link shows once signed in (A8).
"""

import logging

from django.conf import settings
from django.core import mail
from django.db.models import QuerySet
from django.utils import timezone

from accounts.models import User
from accounts.services.roles import board_members
from core.services.mail import MAIL_FAILURES
from documents.models import Document

# Created by the migration documents/0002_document_notification_group.
DOCUMENT_NOTIFICATION_GROUP = "Notifications documents"

logger = logging.getLogger(__name__)


def notification_recipients(uploader: User) -> QuerySet[User]:
    """The active board members of the group, but whoever deposited the document."""
    # A second filter, a second join: in a single one, the condition of the
    # board and that of the group would bear on the same group.
    recipients = board_members().filter(groups__name=DOCUMENT_NOTIFICATION_GROUP)
    return recipients.exclude(pk=uploader.pk)


def notify_document_upload(document_id: int) -> None:
    """Tell the chosen accounts that a document awaits review: one message each,
    all over a single connection.

    The deposit is done already: a failure to send is written to the
    application's journal, and the member who deposited never sees it.
    """
    document = Document.objects.select_related("uploaded_by").get(pk=document_id)
    messages = [
        mail.EmailMessage(_subject(document), _body(document), to=[recipient.email])
        for recipient in notification_recipients(document.uploaded_by)
    ]
    try:
        mail.mailers.default.send_messages(messages)
    except MAIL_FAILURES:
        logger.exception("The notification of document %s could not be sent.", document_id)


def document_link(document: Document) -> str:
    """The address of a document in the board space, which asks to sign in."""
    return f"{settings.SITE_URL}/bureau/documents?document={document.pk}"


def _subject(document: Document) -> str:
    return f"Nouveau document à vérifier : {document.title}"


def _body(document: Document) -> str:
    # Told right after its deposit, by a member: the account is there.
    uploader = document.uploaded_by
    who = uploader.get_full_name() or uploader.email
    deposited = timezone.localtime(document.created_at)
    return (
        f"Un document vient d’être déposé dans l’espace du bureau.\n"
        f"\n"
        f"Titre : {document.title}\n"
        f"Catégorie : {document.get_category_display()}\n"
        f"Déposé par : {who}\n"
        f"Date du dépôt : {deposited:%d/%m/%Y} à {deposited:%H} h {deposited:%M}\n"
        f"\n"
        f"Pour le vérifier (la page demande de se connecter) :\n"
        f"{document_link(document)}\n"
    )
