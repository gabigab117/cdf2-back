from django.shortcuts import get_object_or_404
from ninja import File, Form, Router, Status, UploadedFile

from core.schemas import ErrorOut, ValidationErrorOut
from documents.models import Document
from documents.schemas import DocumentOut, DocumentUploadIn
from documents.services.documents import upload_document
from documents.services.files import PDF, WEBP
from documents.services.serving import file_response

router = Router(tags=["documents"])

# A document's file is not JSON: the operation returns it as it is, and
# declares its content here. Only PDFs and WebP images are stored (D9).
DOCUMENT_FILE = {
    "responses": {
        200: {
            "description": "The document's file",
            "content": {
                media_type: {"schema": {"type": "string", "format": "binary"}}
                for media_type in (PDF, WEBP)
            },
        }
    }
}

# What every operation on an existing document may answer besides its success.
REFUSALS = {401: ErrorOut, 403: ErrorOut, 404: ErrorOut, 422: ValidationErrorOut}


@router.post(
    "/documents",
    response={
        201: DocumentOut,
        400: ErrorOut,
        401: ErrorOut,
        403: ErrorOut,
        422: ValidationErrorOut,
    },
    summary="Deposit a document",
)
def upload(request, file: File[UploadedFile], payload: Form[DocumentUploadIn]):
    """Record a file, as the member classifies it: it awaits review.

    The type is read from the content: a PDF, or an image, converted to WebP.
    """
    return Status(201, upload_document(file, payload, request.auth))


@router.get(
    "/documents/{document_id}/file",
    response={200: None, **REFUSALS},
    openapi_extra=DOCUMENT_FILE,
    summary="Read the file of a document",
)
def read_file(request, document_id: int, download: bool = False):
    """The file, of the type recorded for it: shown in the browser, or downloaded."""
    return file_response(get_object_or_404(Document, pk=document_id), download=download)
