"""`manage.py import_v1_documents`: the take-over of the v1's documents (A1), in production."""

from argparse import ArgumentParser
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from documents.services.v1_import import V1ImportError, import_v1_documents


class Command(BaseCommand):
    help = (
        "Take over the documents of the v1, listed in a CSV file, their files in a "
        "folder. All or nothing; a file imported already is passed over."
    )

    def add_arguments(self, parser: ArgumentParser) -> None:
        parser.add_argument("--csv", type=Path, required=True, help="The CSV file of the v1.")
        parser.add_argument("--files", type=Path, required=True, help="The folder of its files.")
        parser.add_argument(
            "--dry-run", action="store_true", help="Read and check every line, write nothing."
        )

    def handle(self, *args: object, **options: object) -> None:
        dry_run = bool(options["dry_run"])
        try:
            lines = import_v1_documents(options["csv"], options["files"], dry_run=dry_run)
        except V1ImportError as error:
            raise CommandError(f"Nothing was imported. {error}") from error
        new_word = "to import" if dry_run else "imported"
        for line in lines:
            done = "already imported" if line.document is None else new_word
            self.stdout.write(f"Line {line.number}: {done}, « {line.title} ».")
        new = sum(line.document is not None for line in lines)
        summary = f"{len(lines)} documents: {new} {new_word}, "
        summary += f"{len(lines) - new} imported already."
        if dry_run:
            summary += " Dry run: nothing was written."
        self.stdout.write(self.style.SUCCESS(summary))
