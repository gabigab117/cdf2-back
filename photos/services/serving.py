"""How a photo reaches its reader: a board member, or a visitor of the site while the
photo is visible (D17).
"""

from django.http.response import HttpResponseBase
from django.utils.cache import patch_cache_control

from documents.services.files import WEBP
from documents.services.serving import stored_file_response
from photos.models import Photo
from photos.schemas import PhotoRendition


def photo_response(photo: Photo, rendition: PhotoRendition, *, public: bool) -> HttpResponseBase:
    """A size of a photo, shown in the browser."""
    # The name it was sent under may name someone: a visitor is given another.
    name = f"photo-{photo.pk}.webp" if public else photo.original_name
    response = stored_file_response(getattr(photo, rendition), WEBP, download=False, filename=name)
    if public:
        # Checked again at each showing: a photo hidden, unpublished or removed
        # leaves the site at once.
        patch_cache_control(response, no_cache=True)
    else:
        patch_cache_control(response, private=True, no_store=True)
    return response
