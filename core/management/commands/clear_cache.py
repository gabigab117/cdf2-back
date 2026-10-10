"""`manage.py clear_cache`: empties the cache, every night on the server."""

from django.core.cache import cache
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Empty the cache. It only holds the throttle counters, each named after "
        "the address it counts: emptied every night, none outlives the day."
    )

    def handle(self, *args: object, **options: object) -> None:
        # Django has no command for it, and its database cache only deletes an
        # expired row when that row is read again, or once the table holds 300:
        # the counter of an address that never comes back would stay for good.
        cache.clear()
        self.stdout.write(self.style.SUCCESS("Cache emptied."))
