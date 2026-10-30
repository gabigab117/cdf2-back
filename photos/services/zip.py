"""The zip of a selection's images, written while it is sent: an album's images can
weigh hundreds of megabytes, which the server never holds at once.
"""

import zipfile
from collections.abc import Iterator
from pathlib import PurePath

from photos.models import Photo


class _Stream:
    """What the zip is written to: it never seeks, and gives up what it holds as
    the response sends it.
    """

    def __init__(self) -> None:
        self._data = bytearray()

    def write(self, data: bytes) -> int:
        self._data += data
        return len(data)

    def flush(self) -> None:
        pass

    def take(self) -> bytes:
        data, self._data = bytes(self._data), bytearray()
        return data


def zip_images(photos: list[Photo]) -> Iterator[bytes]:
    """The zip of the photos' images, each under its original name, sent image by
    image: the server holds one at a time.

    Stored without compression: a WebP is compressed already.
    """
    stream = _Stream()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_STORED) as archive:
        for photo, name in zip(photos, _names(photos), strict=True):
            with photo.image.open("rb") as image:
                archive.writestr(name, image.read())
            yield stream.take()
    # Its directory, written as it closes.
    yield stream.take()


def _names(photos: list[Photo]) -> Iterator[str]:
    """Each photo's original name; a name given already takes « (2) », « (3) »…, as
    a computer names a copy.
    """
    given: set[str] = set()
    for photo in photos:
        original = PurePath(photo.original_name)
        name, copy = original.name, 1
        while name in given:
            copy += 1
            name = f"{original.stem} ({copy}){original.suffix}"
        given.add(name)
        yield name
