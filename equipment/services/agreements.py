"""The agreement a borrower signed (A16): uploaded as a document « Divers »,
which awaits review like any other, and linked to its loan.
"""

from django.core.files import File
from django.db import transaction

from accounts.models import User
from documents.models import Document, DocumentCategory
from documents.services.documents import TITLE_LENGTH, record_upload
from equipment.models import Loan
from equipment.services.loans import reread


def attach_agreement(loan: Loan, file: File, member: User) -> Loan:
    """Upload the agreement of a loan, as a member does: it takes the link of
    the loan, and a former one stays among the documents. A committee loan has
    none, which its constraint refuses.

    The upload and the link make one record: the board is told of the
    document once both are written.
    """
    document = None
    try:
        with transaction.atomic():
            title = f"Convention signée {loan.number} — {loan.borrower_name}"
            # Cut to the length of a title, it loses a space left at its end.
            title = title[:TITLE_LENGTH].rstrip()
            document = record_upload(
                Document(category=DocumentCategory.MISC, title=title), file, member
            )
            loan.agreement = document
            loan.full_clean()
            loan.save(update_fields=["agreement"])
    except BaseException:
        # The upload undone, its file goes too: record_document only removes
        # it when its own record fails.
        if document is not None:
            document.file.delete(save=False)
        raise
    return reread(loan)
