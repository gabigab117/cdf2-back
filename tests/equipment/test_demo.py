"""The fictitious equipment and loans of the mockup, around its day: 1 October 2026."""

import datetime as dt
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from equipment.models import Equipment, Loan, LoanState
from equipment.services.demo import DEMO_EQUIPMENT, seed_demo_equipment
from equipment.services.states import loan_state
from events.services.demo import seed_demo_events
from tests.equipment.factories import EquipmentFactory, lend

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 10, 1)


@pytest.fixture(autouse=True)
def mockup_day(monkeypatch):
    """Every rule that reads today reads the mockup's day: the services ask
    Django's clock, which this test sets.
    """
    monkeypatch.setattr(timezone, "localdate", lambda *args, **kwargs: TODAY)


def seed():
    seed_demo_events(TODAY)
    return seed_demo_equipment(TODAY)


def test_the_seed_writes_the_equipment_and_the_loans_of_the_mockup():
    """
    Given the demo events, on the mockup's day
    When the equipment of the demonstration is seeded
    Then its 14 equipment and 9 loans are written, each in the state the
    mockup shows, the bench damaged at the school's fête under repair
    """
    inventory = seed()

    assert len(inventory.equipment) == Equipment.objects.count() == len(DEMO_EQUIPMENT) == 14
    states = {(loan.display_name, loan_state(loan, TODAY)) for loan in inventory.loans}
    assert states == {
        ("Halloween des enfants", LoanState.COMMITTEE),
        ("Loto d’automne", LoanState.COMMITTEE),
        ("Marché de Noël", LoanState.COMMITTEE),
        ("Mairie", LoanState.RETURNED),
        ("Parents d’élèves", LoanState.RETURNED),
        ("École du village", LoanState.OUT),
        ("M. Petit", LoanState.TO_PREPARE),
        ("Club de football", LoanState.CONFIRMED),
        ("Comité des fêtes voisin", LoanState.CONFIRMED),
    }
    benches = Equipment.objects.get(name="Bancs pliants")
    school = Loan.objects.get(borrower_name="Parents d’élèves")
    assert (benches.repair_quantity, benches.repair_note) == (
        2,
        f"1 assise fendue.\n1 abîmé au retour du prêt {school.number}.",
    )
    halloween = Loan.objects.get(event__title="Halloween des enfants")
    assert (halloween.start_date, halloween.end_date) == (
        dt.date(2026, 10, 30),
        dt.date(2026, 11, 1),
    )


def test_the_seed_runs_again_and_keeps_a_loan_typed_by_hand():
    """
    Given the demonstration seeded, and a loan typed by hand
    When the seed runs again
    Then the equipment are rewritten, the loans of the demonstration written
    anew, and the loan typed by hand stays
    """
    seed()
    typed = lend(
        Equipment.objects.get(name="Mange-debout"), 2, TODAY, TODAY, borrower_name="Judo club"
    )

    inventory = seed()

    assert Equipment.objects.count() == 14
    assert len(inventory.loans) == 9
    assert Loan.objects.count() == 10
    assert Loan.objects.filter(pk=typed.pk).exists()
    assert Equipment.objects.get(name="Bancs pliants").repair_quantity == 2


def test_a_demo_loan_that_would_take_more_than_is_free_is_left_out():
    """
    Given the 23 tables free all taken on the days of the tournament, by a loan typed by hand
    When the demonstration is seeded
    Then the tournament's loan is left out, as the API would refuse it
    """
    tables = EquipmentFactory(name="Tables pliantes 180 cm", total_quantity=24, repair_quantity=1)
    lend(tables, 23, dt.date(2026, 10, 16), dt.date(2026, 10, 18), borrower_name="Brocante")

    inventory = seed()

    assert "Club de football" not in {loan.display_name for loan in inventory.loans}
    assert len(inventory.loans) == 8


def test_the_command_tells_what_it_wrote(settings):
    """
    Given an environment that allows demo data
    When `manage.py seed_demo` runs, on the mockup's day
    Then it says how many events, equipment and loans it wrote
    """
    settings.DEMO_DATA_ENABLED = True
    out = StringIO()

    call_command("seed_demo", stdout=out)

    assert "9 demo events written." in out.getvalue()
    assert "14 demo equipment and 9 demo loans written." in out.getvalue()
