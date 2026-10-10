"""The agreement a borrower signed (A16): deposited as a document « Divers »,
which awaits review like any other, and linked to its loan.
"""

from django.core.files import File
from django.db import transaction

from accounts.models import User
from documents.models import Document, DocumentCategory
from documents.schemas import DocumentUploadIn
from documents.services.documents import upload_document
from equipment.models import Loan
from equipment.services.loans import loans, with_state

TITLE_LENGTH = Document._meta.get_field("title").max_length


def attach_agreement(loan: Loan, file: File, member: User) -> Loan:
    """Deposit the agreement of a loan, as a member does: it takes the link of
    the loan, and a former one stays among the documents. A committee loan has
    none, which its constraint refuses.

    The deposit and the link make one record: the board is told of the
    document once both are written.
    """
    document = None
    try:
        with transaction.atomic():
            title = f"Convention signée {loan.number} — {loan.borrower_name}"[:TITLE_LENGTH]
            document = upload_document(
                file, DocumentUploadIn(category=DocumentCategory.MISC, title=title), member
            )
            loan.agreement = document
            loan.full_clean()
            loan.save(update_fields=["agreement"])
    except BaseException:
        # The deposit undone, its file goes too: upload_document only removes
        # it when its own record fails.
        if document is not None:
            document.file.delete(save=False)
        raise
    return with_state(loans().get(pk=loan.pk))
