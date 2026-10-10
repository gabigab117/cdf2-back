import factory

from documents.models import Document, DocumentCategory
from tests.accounts.factories import BoardMemberFactory
from tests.documents.samples import PDF


class DocumentFactory(factory.django.DjangoModelFactory):
    """A PDF invoice deposited by a board member, awaiting review.

    Its fingerprint is a distinct number of its own: a test of duplicates sends
    a real file twice.
    """

    class Meta:
        model = Document

    title = factory.Sequence(lambda n: f"Facture — Location sono ({n})")
    category = DocumentCategory.INVOICE
    file = factory.django.FileField(filename="facture.pdf", data=PDF)
    original_name = "facture.pdf"
    mime_type = "application/pdf"
    size = len(PDF)
    sha256 = factory.Sequence(lambda n: f"{n:064x}")
    uploaded_by = factory.SubFactory(BoardMemberFactory)
