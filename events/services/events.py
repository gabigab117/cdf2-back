"""The events the board writes, with their programme and practical info."""

import datetime as dt

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from core.errors import line_errors
from core.text import count_text, french_slug
from events.models import Event, PracticalInfo, ProgrammeItem
from events.schemas import EventIn

# The fields of EventIn that are not copied onto the event as they come.
_NOT_COPIED = {"slug", "lead", "previous_edition", "programme", "practical_infos"}


def event_slug(title: str, starts_at: dt.datetime) -> str:
    """The address an event gets when none is typed: its title and the year it
    starts in Paris, such as "halloween-des-enfants-2026".

    Each edition of a yearly event thus gets its own address.
    """
    return french_slug(f"{title} {timezone.localtime(starts_at).year}")


def create_event(data: EventIn) -> Event:
    """Record a new event, with its programme and practical info."""
    return _save(Event(), data)


def update_event(event: Event, data: EventIn) -> Event:
    """Rewrite an event whole: its programme and practical info are replaced."""
    return _save(event, data)


def delete_event(event: Event) -> None:
    """Delete an event, with its programme and practical info.

    A later edition loses its link to it. Each phase that attaches records to
    events sets its own rule: delete them along, keep them without it, or
    refuse. An event that has ledger entries is refused: its accounts never go
    without a word. The operations of the stock stay, without their event.
    """
    # PROTECT refuses it before any deletion: the transaction stays usable.
    try:
        event.delete()
    except ProtectedError as error:
        entries = len(error.protected_objects)
        lines = count_text(entries, "ligne de trésorerie", "lignes de trésorerie")
        them = "la" if entries == 1 else "les"
        raise ValidationError(
            f"Cet événement a {lines} :"
            f" rattachez-{them} à un autre événement ou au fonctionnement du comité"
            " avant de le supprimer."
        ) from error


@transaction.atomic
def _save(event: Event, data: EventIn) -> Event:
    # Only a lead being chosen must be a board member: whoever has left the
    # board since stays the lead of their events.
    lead_unchanged = event.pk is not None and event.lead_id == data.lead
    for name, value in data.model_dump(exclude=_NOT_COPIED).items():
        setattr(event, name, value)
    event.slug = french_slug(data.slug) if data.slug else event_slug(data.title, data.starts_at)
    event.lead_id = data.lead
    event.previous_edition_id = data.previous_edition
    programme = [
        ProgrammeItem(event=event, sort_order=index, **item.model_dump())
        for index, item in enumerate(data.programme)
    ]
    practical_infos = [
        PracticalInfo(event=event, sort_order=index, **info.model_dump())
        for index, info in enumerate(data.practical_infos)
    ]
    _validate(
        event,
        exclude={"lead"} if lead_unchanged else set(),
        lines={"programme": programme, "practical_infos": practical_infos},
    )
    event.save()
    event.programme.all().delete()
    ProgrammeItem.objects.bulk_create(programme)
    event.practical_infos.all().delete()
    PracticalInfo.objects.bulk_create(practical_infos)
    return event


def _validate(event: Event, exclude: set[str], lines: dict[str, list[models.Model]]) -> None:
    """Check the event and each of its lines before anything is written.

    Every error is reported at once, a line's under its position in its list:
    "programme.2.title".
    """
    errors: dict[str, list[str]] = {}
    try:
        event.full_clean(exclude=exclude)
    except ValidationError as error:
        errors |= error.message_dict
    for name, items in lines.items():
        for index, item in enumerate(items):
            errors |= line_errors(name, index, item, {"event"})
    if errors:
        raise ValidationError(errors)
