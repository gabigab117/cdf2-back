"""`manage.py purge_personal_data`: erases the personal data whose retention
period is over (A9), every night on the server.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from equipment.services.purge import purge_loans
from reservations.services.purge import purge_reservations
from stations.services.purge import purge_volunteers


class Command(BaseCommand):
    help = (
        "Erase the personal data whose retention period is over (A9): a borrower's "
        "phone three months after the return, a person's name and the notes of their "
        "loan a year after, the name and remark of a reservation three months after its "
        "event, a volunteer's name two years after. The totals are kept."
    )

    def handle(self, *args: object, **options: object) -> None:
        # Each purge is one UPDATE and holds alone: a failure leaves the others'
        # work done, and the next night picks up the rest.
        today = timezone.localdate()
        loans = purge_loans(today)
        reservations = purge_reservations(today)
        volunteers = purge_volunteers(today)
        # Counts only: the journal keeps this output for a week.
        self.stdout.write(
            self.style.SUCCESS(
                f"Personal data erased. Phones: {loans.phones}. Borrowers' names: "
                f"{loans.names}. Reservations: {reservations}. Volunteers' names: "
                f"{volunteers}."
            )
        )
