"""The email of a document deposited (D7), sent to the accounts the superuser chose."""

import importlib
import smtplib

import pytest
from django.apps import apps
from django.contrib.auth.models import Group
from django.core.mail.backends.locmem import EmailBackend
from django.db import transaction
from django.utils import timezone

from documents.models import Document, DocumentCategory
from documents.schemas import DocumentUploadIn
from documents.services.documents import upload_document
from documents.services.notifications import DOCUMENT_NOTIFICATION_GROUP
from tests.accounts.factories import BoardMemberFactory, UserFactory, client_of
from tests.documents.samples import pdf, upload

pytestmark = pytest.mark.django_db

DOCUMENTS = "/api/board/documents"

notification_group_migration = importlib.import_module(
    "documents.migrations.0002_document_notification_group"
)


def notified(account):
    """Put an account in the group the superuser fills from the admin."""
    account.groups.add(Group.objects.get(name=DOCUMENT_NOTIFICATION_GROUP))
    return account


def upload_file(member, content=None, title="Facture — Location sono"):
    file = upload(content or pdf(title), "facture-sono.pdf")
    return client_of(member).post(DOCUMENTS, {"file": file, "category": "invoice", "title": title})


def test_the_notification_group_migration_creates_and_removes_the_group():
    """
    Given a database migrated, as on every deployment
    When the group's migration is reversed, then applied again
    Then the group the superuser fills is removed, then created again
    """
    assert Group.objects.filter(name=DOCUMENT_NOTIFICATION_GROUP).exists()

    notification_group_migration.delete_document_notification_group(apps, None)
    assert not Group.objects.filter(name=DOCUMENT_NOTIFICATION_GROUP).exists()

    notification_group_migration.create_document_notification_group(apps, None)
    assert Group.objects.filter(name=DOCUMENT_NOTIFICATION_GROUP).exists()


def test_a_deposit_tells_the_active_board_members_of_the_group_alone(
    mailoutbox, django_capture_on_commit_callbacks
):
    """
    Given, in the group: a board member, a superuser outside the board group,
    an account outside the board, an inactive member, and the member who
    deposits; and a board member outside the group
    When the member deposits a document
    Then the board member and the superuser of the group receive a message
    each, and no one else
    """
    member = notified(BoardMemberFactory(email="julie@example.fr"))
    superuser = notified(UserFactory(email="admin@example.fr", is_superuser=True))
    notified(UserFactory(email="hors-bureau@example.fr"))
    notified(BoardMemberFactory(email="parti@example.fr", is_active=False))
    BoardMemberFactory(email="sans-e-mail@example.fr")
    uploader = notified(BoardMemberFactory(email="camille@example.fr"))

    with django_capture_on_commit_callbacks(execute=True):
        response = upload_file(uploader)

    assert response.status_code == 201
    assert sorted(message.to[0] for message in mailoutbox) == [superuser.email, member.email]
    assert all(len(message.to) == 1 for message in mailoutbox)


def test_the_messages_go_over_a_single_connection(
    mailoutbox, django_capture_on_commit_callbacks, monkeypatch
):
    """
    Given two accounts to tell
    When a document is deposited
    Then their messages are sent together, over one connection
    """
    notified(BoardMemberFactory())
    notified(BoardMemberFactory())
    sends = []
    send_messages = EmailBackend.send_messages

    def counted(self, messages):
        sends.append(len(messages))
        return send_messages(self, messages)

    monkeypatch.setattr(EmailBackend, "send_messages", counted)

    with django_capture_on_commit_callbacks(execute=True):
        upload_file(BoardMemberFactory())

    assert sends == [2]


def test_the_message_names_the_document_and_leads_to_it(
    mailoutbox, django_capture_on_commit_callbacks, settings
):
    """
    Given the site's address, and Camille Martin who deposits an invoice
    When the message goes
    Then its subject names the document, and its text its category, who
    deposited it and when, in Paris time, then the link to it, which asks to
    sign in; it holds neither the file nor its content
    """
    settings.SITE_URL = "https://bureau.example.org"
    notified(BoardMemberFactory())

    with django_capture_on_commit_callbacks(execute=True):
        upload_file(BoardMemberFactory(first_name="Camille", last_name="Martin"))

    [message] = mailoutbox
    document = Document.objects.get()
    deposited = timezone.localtime(document.created_at)
    assert message.subject == "Nouveau document à vérifier : Facture — Location sono"
    assert message.body == (
        "Un document vient d’être déposé dans l’espace du bureau.\n"
        "\n"
        "Titre : Facture — Location sono\n"
        "Catégorie : Facture\n"
        "Déposé par : Camille Martin\n"
        f"Date du dépôt : {deposited:%d/%m/%Y} à {deposited:%H} h {deposited:%M}\n"
        "\n"
        "Pour le vérifier (la page demande de se connecter) :\n"
        f"https://bureau.example.org/bureau/documents?document={document.pk}\n"
    )
    assert message.attachments == []
    assert message.from_email == settings.DEFAULT_FROM_EMAIL


def test_a_member_without_a_name_is_named_by_their_address(
    mailoutbox, django_capture_on_commit_callbacks
):
    notified(BoardMemberFactory())

    with django_capture_on_commit_callbacks(execute=True):
        upload_file(BoardMemberFactory(first_name="", last_name="", email="tresor@example.fr"))

    assert "Déposé par : tresor@example.fr\n" in mailoutbox[0].body


def test_a_deposit_undone_tells_no_one(mailoutbox, django_capture_on_commit_callbacks):
    """
    Given an account to tell
    When a deposit is undone within the transaction that made it
    Then no message goes
    """
    notified(BoardMemberFactory())
    member = BoardMemberFactory()
    data = DocumentUploadIn(category=DocumentCategory.INVOICE)

    with (
        django_capture_on_commit_callbacks(execute=True),
        pytest.raises(RuntimeError),
        transaction.atomic(),
    ):
        upload_document(upload(pdf()), data, member)
        raise RuntimeError("undone")

    assert mailoutbox == []


@pytest.mark.parametrize(
    "failure",
    [
        smtplib.SMTPServerDisconnected("Connection unexpectedly closed"),
        ConnectionRefusedError("Connection refused"),
        TimeoutError("timed out"),
        ValueError("Invalid address ''"),
    ],
    ids=["hung-up", "refused", "timed-out", "no-sender"],
)
def test_a_failure_to_send_leaves_the_deposit_done_and_is_written_to_the_journal(
    failure, mailoutbox, django_capture_on_commit_callbacks, monkeypatch, caplog
):
    """
    Given the SMTP server that hangs up, refuses the connection or does not
    answer, or a sender left empty, which the SMTP backend refuses to send with
    When a member deposits a document
    Then the deposit is done, the member told nothing of it
    And the failure is written to the application's journal
    """
    notified(BoardMemberFactory())

    def failed(self, messages):
        raise failure

    monkeypatch.setattr(EmailBackend, "send_messages", failed)

    with django_capture_on_commit_callbacks(execute=True):
        response = upload_file(BoardMemberFactory())

    assert response.status_code == 201
    document = Document.objects.get()
    [record] = [record for record in caplog.records if record.name.startswith("documents")]
    assert record.levelname == "ERROR"
    assert record.getMessage() == f"The notification of document {document.pk} could not be sent."
    assert record.exc_info[1] is failure
