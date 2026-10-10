"""`manage.py import_v1_equipment`: the take-over of the v1's inventory (A1), in production."""

from argparse import ArgumentParser
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from equipment.services.v1_import import V1ImportError, import_v1_equipment


class Command(BaseCommand):
    help = (
        "Take over the inventory of the v1, exported to JSON, with the category, "
        "place and value a mapping sheet gives each equipment. All or nothing; an "
        "equipment whose name exists already is passed over."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument(
            "--inventory", type=Path, required=True, help="The JSON export of the v1."
        )
        parser.add_argument("--mapping", type=Path, required=True, help="The CSV mapping sheet.")
        parser.add_argument(
            "--dry-run", action="store_true", help="Read and check everything, write nothing."
        )

    def handle(self, *args: object, **options: object) -> None:
        dry_run = bool(options["dry_run"])
        try:
            lines = import_v1_equipment(options["inventory"], options["mapping"], dry_run=dry_run)
        except V1ImportError as error:
            raise CommandError(f"Nothing was imported. {error}") from error
        new_word = "to import" if dry_run else "imported"
        for line in lines:
            done = "exists already" if line.equipment is None else new_word
            self.stdout.write(f"« {line.name} », {line.quantity} pieces: {done}.")
        new = sum(line.equipment is not None for line in lines)
        units = sum(line.quantity for line in lines)
        summary = f"{len(lines)} equipment items, {units} units: {new} {new_word}, "
        summary += f"{len(lines) - new} existing already."
        if dry_run:
            summary += " Dry run: nothing was written."
        self.stdout.write(self.style.SUCCESS(summary))
