"""The agreement a borrower signed, deposited from its loan as a document (A16)."""

import pytest
from django.contrib.auth.models import Group
from django.core.serializers.json import DjangoJSONEncoder

from documents.models import Document, DocumentCategory, DocumentStatus
from documents.services.notifications import DOCUMENT_NOTIFICATION_GROUP
from equipment.models import Loan
from tests.accounts.factories import BoardMemberFactory
from tests.documents.samples import pdf, upload
from tests.equipment.factories import CommitteeLoanFactory, LoanFactory

pytestmark = pytest.mark.django_db


def url(loan_id):
    return f"/api/board/loans/{loan_id}/agreement"


def deposit(client, loan, content=None, name="convention.pdf"):
    return client.post(url(loan.id), {"file": upload(content or pdf("Convention signée"), name)})


def stored(private_files):
    """The files written to the private folder."""
    return [path for path in private_files.rglob("*") if path.is_file()]


def test_a_member_deposits_the_agreement_a_borrower_signed(board_client, board_member):
    """
    Given a loan to the football club
    When a member deposits the agreement the club signed
    Then it is a document « Divers » awaiting review, titled after the loan,
    and the loan leads to it
    """
    loan = LoanFactory(number="P-2026-018")

    response = deposit(board_client, loan)

    assert response.status_code == 200
    document = Document.objects.get()
    assert (
        document.category,
        document.status,
        document.title,
        document.uploaded_by,
        document.event,
    ) == (
        DocumentCategory.MISC,
        DocumentStatus.TO_REVIEW,
        "Convention signée P-2026-018 — Club de football",
        board_member,
        None,
    )
    assert response.json()["agreement"] == {
        "id": document.id,
        "title": "Convention signée P-2026-018 — Club de football",
        "created_at": DjangoJSONEncoder().default(document.created_at),
    }
    assert Loan.objects.get().agreement == document


def test_a_new_agreement_takes_the_link_and_the_former_stays(board_client):
    """
    Given a loan whose signed agreement was deposited
    When a member deposits another
    Then the loan leads to the new one, and the former stays among the documents
    """
    loan = LoanFactory()
    former = deposit(board_client, loan, pdf("Première signature")).json()["agreement"]

    response = deposit(board_client, loan, pdf("Seconde signature"))

    assert response.json()["agreement"]["id"] != former["id"]
    assert Loan.objects.get().agreement_id == response.json()["agreement"]["id"]
    assert Document.objects.filter(pk=former["id"]).exists()


def test_a_committee_loan_has_no_agreement(board_client, private_files):
    """
    Given the equipment an event keeps
    When a member deposits an agreement for it
    Then it is refused, and neither the document nor its file is kept
    """
    loan = CommitteeLoanFactory()

    response = deposit(board_client, loan)

    assert response.status_code == 422
    assert response.json() == {
        "detail": [
            {
                "type": "validation_error",
                "loc": ["body"],
                "msg": "Un usage comité n’a pas de convention.",
            }
        ]
    }
    assert not Document.objects.exists()
    assert stored(private_files) == []
    assert Loan.objects.get().agreement is None


def test_a_file_the_documents_refuse_is_refused_under_its_field(board_client, private_files):
    """
    Given a loan to the football club
    When a member deposits a text file as its agreement
    Then it is refused under the file, as any document, and the loan keeps none
    """
    loan = LoanFactory()

    response = deposit(board_client, loan, b"Lu et approuve", "convention.txt")

    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [["body", "file"]]
    assert Loan.objects.get().agreement is None
    assert stored(private_files) == []


def test_an_agreement_without_a_file_is_refused(board_client):
    response = board_client.post(url(LoanFactory().id))

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"type": "missing", "loc": ["file", "file"], "msg": "Ce champ est obligatoire."}
    ]


def test_the_title_is_cut_to_the_length_of_a_document_title(board_client):
    """
    Given a loan to a borrower of a name as long as a field takes
    When its agreement is deposited
    Then its title is cut to the 200 characters a document title takes
    """
    loan = LoanFactory(borrower_name="A" * 200)

    response = deposit(board_client, loan)

    assert response.status_code == 200
    assert len(Document.objects.get().title) == 200


def test_the_board_is_told_of_the_agreement_once_it_is_linked(
    board_client, mailoutbox, django_capture_on_commit_callbacks
):
    """
    Given a member of the group that hears of each document deposited
    When the agreement of a loan is deposited
    Then they are told of it, as of any document
    """
    member = BoardMemberFactory(email="julie@example.fr")
    member.groups.add(Group.objects.get(name=DOCUMENT_NOTIFICATION_GROUP))

    with django_capture_on_commit_callbacks(execute=True):
        deposit(board_client, LoanFactory(number="P-2026-018"))

    assert [(message.to, message.subject) for message in mailoutbox] == [
        (
            ["julie@example.fr"],
            "Nouveau document à vérifier : Convention signée P-2026-018 — Club de football",
        )
    ]


def test_a_deleted_agreement_leaves_the_loan_without_one(board_client):
    """
    Given a loan whose signed agreement was deposited
    When a member deletes that document
    Then the loan is kept, without an agreement
    """
    loan = LoanFactory()
    agreement = deposit(board_client, loan).json()["agreement"]

    response = board_client.delete(f"/api/board/documents/{agreement['id']}")

    assert response.status_code == 204
    assert Loan.objects.get().agreement is None


def test_an_unknown_loan_is_not_found(board_client):
    response = board_client.post(url(999), {"file": upload(pdf())})

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}
