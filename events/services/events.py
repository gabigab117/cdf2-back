"""The events the board writes, with their programme and practical info."""

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify

from events.models import Event, PracticalInfo, ProgrammeItem
from events.schemas import EventIn

# slugify() drops the letters Unicode does not decompose, French ligatures among
# them ("œufs" would become "ufs"), and glues the words an apostrophe joins
# ("dautomne"): both are spelled out beforehand.
_SLUG_SPELLING = str.maketrans({"œ": "oe", "Œ": "Oe", "æ": "ae", "Æ": "Ae", "'": " ", "’": " "})

# The fields of EventIn that are not copied onto the event as they come.
_NOT_COPIED = {"slug", "lead", "previous_edition", "programme", "practical_infos"}


def create_event(data: EventIn) -> Event:
    """Record a new event, with its programme and practical info."""
    return _save(Event(), data)


def update_event(event: Event, data: EventIn) -> Event:
    """Rewrite an event whole: its programme and practical info are replaced."""
    return _save(event, data)


def delete_event(event: Event) -> None:
    """Delete an event, with its programme and practical info.

    A later edition loses its link to it. Each phase that attaches records to
    events sets its own rule: delete them along, or refuse.
    """
    event.delete()


@transaction.atomic
def _save(event: Event, data: EventIn) -> Event:
    # Only a lead being chosen must be a board member: whoever has left the
    # board since stays the lead of their events.
    lead_unchanged = event.pk is not None and event.lead_id == data.lead
    for name, value in data.model_dump(exclude=_NOT_COPIED).items():
        setattr(event, name, value)
    year = timezone.localtime(data.starts_at).year
    event.slug = slugify((data.slug or f"{data.title} {year}").translate(_SLUG_SPELLING))
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
            try:
                item.full_clean(exclude={"event"})
            except ValidationError as error:
                for field, messages in error.message_dict.items():
                    errors[f"{name}.{index}.{field}"] = messages
    if errors:
        raise ValidationError(errors)
