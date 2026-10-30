"""`manage.py seed_demo`: the fictitious events, equipment, loans and albums of the
mockup, for the preproduction.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from equipment.services.demo import seed_demo_equipment
from events.services.demo import seed_demo_events
from photos.services.demo import seed_demo_albums


class Command(BaseCommand):
    help = (
        "Write the fictitious events of the mockup, published, then its equipment and "
        "loans, around today, and its albums of drawn photos. "
        "Refused unless the environment sets DEMO_DATA_ENABLED: never in production."
    )

    def handle(self, *args: object, **options: object) -> None:
        if not settings.DEMO_DATA_ENABLED:
            raise CommandError(
                "Demo data is not allowed here: DEMO_DATA_ENABLED is not set in the environment."
            )
        today = timezone.localdate()
        events = seed_demo_events(today)
        self.stdout.write(self.style.SUCCESS(f"{len(events)} demo events written."))
        inventory = seed_demo_equipment(today)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(inventory.equipment)} demo equipment and {len(inventory.loans)} "
                "demo loans written."
            )
        )
        albums = seed_demo_albums(today)
        self.stdout.write(
            self.style.SUCCESS(
                f"{len(albums.albums)} demo albums and {albums.photos} demo photos written."
            )
        )
