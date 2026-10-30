"""The cover of an event (D17): a photo of its albums or of its previous edition's,
shown on the site only while the photo is.
"""

from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db.models import QuerySet

from events.models import Event
from photos.models import Album, Photo
from photos.services.photos import albums, visible_photos

NOT_A_CHOICE = "Choisissez une photo des albums de l’événement ou de son édition précédente."


@dataclass(frozen=True)
class EventCover:
    """An event's cover, whether the site shows it, and the albums it is chosen from."""

    cover: int | None
    visible: bool
    albums: list[Album]


def cover_choices(event: Event) -> QuerySet[Album]:
    """The albums an event's cover is chosen from: its own and its previous
    edition's, the latest first. The single rule of the choice, read and checked.
    """
    editions = [event.pk]
    if event.previous_edition_id is not None:
        editions.append(event.previous_edition_id)
    return albums().filter(event__in=editions)


def event_cover(event: Event) -> EventCover:
    return EventCover(
        cover=event.cover_id,
        visible=event.cover_id is not None and visible_photos().filter(pk=event.cover_id).exists(),
        albums=list(cover_choices(event)),
    )


def set_event_cover(event: Event, cover: int | None) -> EventCover:
    """Choose an event's cover among the photos of its cover choices, or none."""
    choices = Photo.objects.filter(album__in=cover_choices(event))
    if cover is not None and not choices.filter(pk=cover).exists():
        raise ValidationError({"cover": NOT_A_CHOICE})
    event.cover_id = cover
    # The date of the event's last change stays, as for its capacity: the cover
    # is chosen apart from it.
    event.save(update_fields=["cover"])
    return event_cover(event)
