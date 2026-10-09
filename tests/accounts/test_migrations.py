import importlib

import pytest
from django.apps import apps
from django.contrib.auth.models import Group

from accounts.services.roles import BOARD_GROUP

pytestmark = pytest.mark.django_db

board_group_migration = importlib.import_module("accounts.migrations.0003_board_group")


def test_the_board_group_migration_creates_and_removes_the_group():
    """
    Given a database migrated, as on every deployment
    When the board group migration is reversed, then applied again
    Then the group the code expects is removed, then created again
    """
    assert Group.objects.filter(name=BOARD_GROUP).exists()

    board_group_migration.delete_board_group(apps, None)
    assert not Group.objects.filter(name=BOARD_GROUP).exists()

    board_group_migration.create_board_group(apps, None)
    assert Group.objects.filter(name=BOARD_GROUP).exists()
