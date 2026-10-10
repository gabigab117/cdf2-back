"""`manage.py seed_demo`: the fictitious events, equipment and loans of the mockup,
for the preproduction.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from equipment.services.demo import seed_demo_equipment
from events.services.demo import seed_demo_events


class Command(BaseCommand):
    help = (
        "Write the fictitious events of the mockup, published, then its equipment and "
        "loans, around today. "
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
