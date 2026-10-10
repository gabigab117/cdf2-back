from django.shortcuts import get_object_or_404
from ninja import File, Form, Query, Router, Status, UploadedFile
from ninja.pagination import paginate

from core.schemas import ErrorOut, ValidationErrorOut
from documents.models import Document
from documents.schemas import (
    DocumentCountsOut,
    DocumentFilters,
    DocumentIn,
    DocumentItemOut,
    DocumentListFilters,
    DocumentOut,
    DocumentUploadIn,
)
from documents.services.documents import (
    delete_document,
    document_counts,
    documents,
    listed_documents,
    update_document,
    upload_document,
    validate_document,
)
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


@router.get(
    "/documents",
    response={200: list[DocumentItemOut], 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="List the documents",
)
@paginate
def list_documents(request, filters: Query[DocumentListFilters]):
    """The documents, by page, the latest date first: a search keeps those holding
    its words, in their texts, amount or event.
    """
    return filters.filter(listed_documents())


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


# Declared before the operations on /documents/{document_id}: Ninja tries the
# paths in their order, and the id would take "counts" for itself.
@router.get(
    "/documents/counts",
    response={200: DocumentCountsOut, 401: ErrorOut, 403: ErrorOut, 422: ValidationErrorOut},
    summary="Count the documents by category",
)
def counts(request, filters: Query[DocumentFilters]):
    """How many documents answer a search, in all and by category, whatever the
    category shown: the counts of the list's chips, whole.
    """
    return document_counts(filters.filter(listed_documents()))


@router.get(
    "/documents/{document_id}",
    response={200: DocumentOut, **REFUSALS},
    summary="Read a document",
)
def read(request, document_id: int):
    return get_object_or_404(documents(), pk=document_id)


@router.put(
    "/documents/{document_id}",
    response={200: DocumentOut, 400: ErrorOut, **REFUSALS},
    summary="Correct a document",
)
def update(request, document_id: int, payload: DocumentIn):
    """Rewrite a document whole: how it is classified, and its fields."""
    return update_document(get_object_or_404(Document, pk=document_id), payload)


@router.delete(
    "/documents/{document_id}",
    response={204: None, **REFUSALS},
    summary="Delete a document",
)
def delete(request, document_id: int):
    """Delete a document and its file."""
    delete_document(get_object_or_404(Document, pk=document_id))
    return Status(204, None)


@router.post(
    "/documents/{document_id}/validate",
    response={200: DocumentOut, **REFUSALS},
    summary="Validate a document",
)
def validate(request, document_id: int):
    """Validate a document awaiting review: minutes create the tasks they list."""
    return validate_document(get_object_or_404(Document, pk=document_id), request.auth)


@router.get(
    "/documents/{document_id}/file",
    response={200: None, **REFUSALS},
    openapi_extra=DOCUMENT_FILE,
    summary="Read the file of a document",
)
def read_file(request, document_id: int, download: bool = False):
    """The file, of the type recorded for it: shown in the browser, or downloaded."""
    return file_response(get_object_or_404(Document, pk=document_id), download=download)
