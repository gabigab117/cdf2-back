"""The albums the site shows (D17): those with a visible photo, which only a
published album has. They name no one.
"""

from django.db.models import Count, OuterRef, Prefetch, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce

from events.models import Event
from photos.models import Album
from photos.services.photos import ALBUM_ORDER, PHOTO_ORDER, visible_cover, visible_photos

# How many photos of its previous edition's album an event's page shows, under
# « L'an dernier ».
PREVIOUS_EDITION_PHOTOS = 6


def public_albums() -> QuerySet[Album]:
    """The albums of the site, the latest first, with their number of visible photos
    and their public cover: their own while visible, else their first visible
    photo.
    """
    visible = visible_photos()
    first = visible.filter(album=OuterRef("pk")).order_by(*PHOTO_ORDER).values("pk")[:1]
    return (
        Album.objects.annotate(
            photos_count=Count("photos", filter=Q(photos__in=visible)),
            public_cover=Coalesce(visible_cover(), Subquery(first)),
        )
        .filter(photos_count__gt=0)
        .order_by(*ALBUM_ORDER)
    )


def public_albums_with_photos() -> QuerySet[Album]:
    """The albums of the site, each with its visible photos, in order."""
    return public_albums().prefetch_related(_prefetch_visible_photos())


def previous_edition_album(event: Event) -> Album | None:
    """« L'an dernier »: the latest album of the site of an event's previous edition,
    with its first visible photos, if it has one.
    """
    if event.previous_edition_id is None:
        return None
    return (
        public_albums()
        .filter(event=event.previous_edition_id)
        .prefetch_related(_prefetch_visible_photos(PREVIOUS_EDITION_PHOTOS))
        .first()
    )


def _prefetch_visible_photos(count: int | None = None) -> Prefetch:
    # A slice to None sets no limit: the page of an album reads them all.
    photos = visible_photos().order_by(*PHOTO_ORDER)[:count]
    return Prefetch("photos", queryset=photos, to_attr="visible_photos")
