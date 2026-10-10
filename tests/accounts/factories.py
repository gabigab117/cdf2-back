import factory
from django.contrib.auth.models import Group

from accounts.models import BoardPosition, User
from accounts.services.roles import BOARD_GROUP

PASSWORD = "a-long-password-2026"


class UserFactory(factory.django.DjangoModelFactory):
    """An active account, outside the board."""

    class Meta:
        model = User

    email = factory.Sequence(lambda n: f"member{n}@example.fr")
    first_name = "Camille"
    last_name = "Martin"
    password = factory.django.Password(PASSWORD)


class BoardMemberFactory(UserFactory):
    """An active account of the board group."""

    class Meta:
        # Adding the group does not require saving the account again.
        skip_postgeneration_save = True

    position = BoardPosition.TREASURER

    @factory.post_generation
    def board_group(self, create, extracted, **kwargs):
        if create:
            self.groups.add(Group.objects.get(name=BOARD_GROUP))
