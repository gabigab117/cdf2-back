"""How a document's file reaches a board member, once the API has checked who asks
(A8).

In development Django sends the file itself. On the server it only answers
with the file's address in nginx's internal location: nginx sends it, a
location that never answers a request of its own.
"""

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.http.response import HttpResponseBase
from django.utils.cache import patch_cache_control
from django.utils.http import content_disposition_header

from documents.models import Document


def file_response(document: Document, *, download: bool) -> HttpResponseBase:
    """The file of a document, of the type recorded for it, shown in the browser
    or downloaded under the name it was deposited with.
    """
    prefix = settings.PRIVATE_FILES_ACCEL_PREFIX
    if prefix:
        response = HttpResponse(
            content_type=document.mime_type,
            headers={
                "X-Accel-Redirect": f"{prefix}{document.file.name}",
                "Content-Disposition": content_disposition_header(download, document.original_name),
            },
        )
    else:
        response = FileResponse(
            document.file.open("rb"),
            content_type=document.mime_type,
            as_attachment=download,
            filename=document.original_name,
        )
    # Invoices, bank statements: no cache keeps a copy.
    patch_cache_control(response, private=True, no_store=True)
    return response
