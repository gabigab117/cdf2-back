"""The fictitious albums of the mockup, which the preproduction shows (`seed_demo`).

Their photos are drawn by Pillow: a sky, hills and bunting, with lanterns by
night. They show no one, as the repositories are public, and are the same at
every run. They are added through the services, as a member would add them, and
go through the real processing.
"""

import datetime as dt
import random
from dataclasses import dataclass
from io import BytesIO

from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone
from PIL import Image, ImageDraw

from events.models import Event
from events.services.periods import events_in_period
from photos.models import Album
from photos.schemas import AlbumIn
from photos.services.covers import set_event_cover
from photos.services.photos import (
    create_album,
    delete_album,
    publish_album,
    set_album_cover,
    set_hidden,
    set_image_rights_to_review,
    upload_photo,
)

type Color = tuple[int, int, int]

YEAR = dt.timedelta(days=365)

# Small enough for the preproduction's single processor to treat them quickly.
DEMO_SIZE = (1600, 1067)

FLAG_COLORS: list[Color] = [(214, 69, 65), (45, 75, 200), (240, 190, 50), (60, 160, 90)]
LANTERN_COLORS: list[Color] = [(255, 200, 90), (255, 150, 70), (250, 230, 140)]


@dataclass(frozen=True)
class DemoAlbum:
    """An album of the mockup, of a past demo event or of the committee's life."""

    # Its title; « {year} » takes the year of its day.
    title: str
    # The title of its past demo event, or none.
    event: str | None
    photos: int
    published: bool
    # Its sky, from the top to the horizon, and its ground.
    sky: tuple[Color, Color]
    ground: Color
    night: bool = False
    # The places of its photos awaiting a check of their image rights, and of
    # those hidden from the site.
    to_review: tuple[int, ...] = ()
    hidden: tuple[int, ...] = ()


DEMO_ALBUMS = [
    DemoAlbum(
        "Brocante {year}",
        "Brocante",
        photos=12,
        published=True,
        sky=((110, 165, 230), (225, 236, 246)),
        ground=(110, 150, 80),
        to_review=(3, 8),
        hidden=(10,),
    ),
    DemoAlbum(
        "Fête du 14 juillet",
        "Fête du 14 juillet",
        photos=8,
        published=True,
        sky=((25, 30, 80), (205, 95, 70)),
        ground=(50, 62, 50),
        night=True,
    ),
    DemoAlbum(
        "Feu de la Saint-Jean",
        "Feu de la Saint-Jean",
        photos=6,
        published=False,
        sky=((15, 20, 48), (130, 62, 48)),
        ground=(42, 46, 36),
        night=True,
    ),
    DemoAlbum(
        "Chasse aux œufs",
        "Chasse aux œufs",
        # More than « L'an dernier » shows on the page of the egg hunt to come.
        photos=10,
        published=True,
        sky=((150, 200, 240), (236, 242, 226)),
        ground=(120, 180, 90),
    ),
    DemoAlbum(
        "Coulisses du bureau",
        None,
        photos=4,
        published=False,
        sky=((236, 226, 210), (250, 245, 236)),
        ground=(170, 130, 90),
    ),
]

# The demo event to come whose cover is its previous edition's album's.
DEMO_COVER = "Chasse aux œufs"


@dataclass(frozen=True)
class DemoAlbums:
    albums: list[Album]
    photos: int


@transaction.atomic
def seed_demo_albums(today: dt.date) -> DemoAlbums:
    """Write the albums of the mockup, each on the day of its past demo event, and the
    cover of an event to come.

    An album of the demonstration is written anew, its files removed once that is
    done; an album added by hand under another title stays. The album of an event's earlier edition,
    from a run of another year, stays too.
    """
    albums = []
    number = 0
    for demo in DEMO_ALBUMS:
        event = events_in_period("past").filter(title=demo.event).first() if demo.event else None
        # Of no event, a year back: the last of the list, as in the mockup.
        day = timezone.localtime(event.starts_at).date() if event else today - YEAR
        title = demo.title.format(year=day.year)
        for album in Album.objects.filter(title=title):
            delete_album(album)
        albums.append(_album(demo, title, day, event, number))
        number += demo.photos
    # The demo events are written first: the event to come is there, with its
    # previous edition.
    upcoming = events_in_period("upcoming").get(title=DEMO_COVER)
    previous = next(album for album in albums if album.event_id == upcoming.previous_edition_id)
    set_event_cover(upcoming, previous.cover_id)
    return DemoAlbums(albums, number)


def _album(demo: DemoAlbum, title: str, day: dt.date, event: Event | None, number: int) -> Album:
    album = create_album(AlbumIn(title=title, date=day, event=event.pk if event else None))
    ids = [
        upload_photo(album, _file(f"{title} {place}", demo, number + place + 1), None).pk
        for place in range(demo.photos)
    ]
    set_album_cover(album, ids[0])
    publish_album(album, demo.published)
    if demo.to_review:
        set_image_rights_to_review(album, [ids[place] for place in demo.to_review], True)
    if demo.hidden:
        set_hidden(album, [ids[place] for place in demo.hidden], True)
    return album


def _file(seed: str, demo: DemoAlbum, number: int) -> ContentFile:
    """A JPEG of a landscape, as a camera names it, drawn the same at every run of
    its seed.
    """
    chance = random.Random(seed)
    width, height = DEMO_SIZE
    image = Image.new("RGB", DEMO_SIZE, demo.ground)
    draw = ImageDraw.Draw(image)
    horizon = int(height * chance.uniform(0.55, 0.7))
    for y in range(horizon):
        draw.line([(0, y), (width, y)], fill=_mix(*demo.sky, y / horizon))
    # A moon and stars by night, a sun by day.
    if demo.night:
        for _ in range(40):
            x, y = chance.randrange(width), chance.randrange(horizon // 2)
            draw.ellipse([x, y, x + 3, y + 3], fill=(245, 245, 230))
    radius = height // 14
    x, y = chance.randrange(radius, width - radius), chance.randrange(radius, horizon // 2)
    draw.ellipse([x - radius, y - radius, x + radius, y + radius], fill=(250, 240, 200))
    # Hills, the farthest first and lightest.
    step = width // 6
    for layer in range(3):
        base = horizon + layer * height // 20
        tops = [(x, base - chance.randrange(height // 6)) for x in range(0, width + step, step)]
        shade = _mix(demo.ground, (0, 0, 0), layer * 0.15)
        draw.polygon([(0, height), *tops, (width, height)], fill=shade)
    # Bunting across the sky, with lanterns by night.
    left, right = (chance.randrange(height // 8, height // 3) for _ in range(2))
    for place in range(13):
        x = width * place // 12
        # The cord sags between its two ends.
        sag = int(height / 12 * (1 - ((place - 6) / 6) ** 2))
        y = left + (right - left) * place // 12 + sag
        if demo.night:
            draw.ellipse([x - 14, y, x + 14, y + 28], fill=chance.choice(LANTERN_COLORS))
        else:
            draw.polygon([(x - 22, y), (x + 22, y), (x, y + 48)], fill=chance.choice(FLAG_COLORS))
    buffer = BytesIO()
    image.save(buffer, "JPEG", quality=85)
    return ContentFile(buffer.getvalue(), name=f"IMG_{number:04}.jpg")


def _mix(start: Color, end: Color, share: float) -> Color:
    return tuple(round(a + (b - a) * share) for a, b in zip(start, end, strict=True))
