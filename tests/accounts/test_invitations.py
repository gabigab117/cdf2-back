"""The accounts of the board (5.9): the superuser invites a member, who chooses
their password from the link of the email.
"""

import importlib
import re
import smtplib

import pytest
from django.apps import apps
from django.contrib.auth.tokens import default_token_generator
from django.core.mail.backends.locmem import EmailBackend
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from ninja_jwt.tokens import AccessToken

from accounts.models import AccountState, BoardPosition, User
from accounts.schemas import PasswordIn
from accounts.services.invitations import INVALID_LINK, set_password
from accounts.services.roles import is_board_member
from tests.accounts.factories import PASSWORD, BoardMemberFactory, UserFactory

pytestmark = pytest.mark.django_db

ACCOUNTS = "/api/board/accounts"
PASSWORD_LINK = "/api/auth/password-link"
CHOOSE_PASSWORD = "/api/auth/password"
LOGIN = "/api/auth/login"

NEW_PASSWORD = "Une-fanfare-sous-les-tilleuls"

clear_positions_migration = importlib.import_module(
    "accounts.migrations.0005_clear_unknown_positions"
)


def client_of(account):
    return Client(headers={"Authorization": f"Bearer {AccessToken.for_user(account)}"})


@pytest.fixture
def superuser(db):
    return UserFactory(
        email="gabriel@example.fr", first_name="Gabriel", last_name="T.", is_superuser=True
    )


@pytest.fixture
def superuser_client(superuser):
    return client_of(superuser)


def invitation(**changes):
    return {
        "email": "Julie.Petit@Example.fr",
        "first_name": "Julie",
        "last_name": "Petit",
        "position": "secretary",
        **changes,
    }


def link_of(message):
    """The uid and token of the link an email gives, after its "#"."""
    uid, token = re.search(r"/choisir-mot-de-passe#([^.\s]+)\.(\S+)", message.body).groups()
    return {"uid": uid, "token": token}


def choose(client, link, password=NEW_PASSWORD, confirmation=None):
    return client.post(
        CHOOSE_PASSWORD,
        {**link, "password": password, "confirmation": confirmation or password},
        content_type="application/json",
    )


def signs_in(email, password):
    response = Client().post(
        LOGIN, {"email": email, "password": password}, content_type="application/json"
    )
    return response.status_code == 200


def forged(token):
    """A token whose last character changed, whatever it was."""
    return f"{token[:-1]}{'b' if token.endswith('a') else 'a'}"


def invalid_link():
    return {"detail": [{"type": "validation_error", "loc": ["body"], "msg": INVALID_LINK}]}


# Access


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", ACCOUNTS), ("post", ACCOUNTS), ("post", f"{ACCOUNTS}/1/link")],
)
def test_the_accounts_are_refused_to_an_anonymous_visitor(client, method, path):
    response = getattr(client, method)(path)

    assert response.status_code == 401


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", ACCOUNTS), ("post", ACCOUNTS), ("post", f"{ACCOUNTS}/1/link")],
)
def test_the_accounts_are_the_superusers_alone(board_client, method, path):
    """
    Given a board member who is not the superuser
    When they read the accounts, invite a member or send a link
    Then the API refuses with a 403 of its own
    """
    response = getattr(board_client, method)(path)

    assert response.status_code == 403
    assert response.json() == {"detail": "Accès réservé à l’administrateur des comptes."}


def test_me_tells_the_superuser(superuser_client):
    response = superuser_client.get("/api/auth/me")

    assert (response.json()["is_superuser"], response.json()["position"]) == (True, "")


# Invitation


def test_the_superuser_invites_a_board_member(superuser_client, mailoutbox, settings):
    """
    Given the superuser
    When they invite Julie Petit, secretary, her address typed with capitals
    Then her account is active, in the board group, neither staff nor superuser,
    without a usable password, her address lower-cased
    And she receives one email, whose link leads to the page to choose her
    password, for seven days
    """
    settings.SITE_URL = "https://site.example"

    response = superuser_client.post(ACCOUNTS, invitation(), content_type="application/json")

    assert response.status_code == 201
    julie = User.objects.get(email="julie.petit@example.fr")
    assert (julie.is_active, julie.is_staff, julie.is_superuser) == (True, False, False)
    assert not julie.has_usable_password()
    assert is_board_member(julie)
    assert julie.position == BoardPosition.SECRETARY
    assert response.json() == {
        "account": {
            "id": julie.id,
            "email": "julie.petit@example.fr",
            "first_name": "Julie",
            "last_name": "Petit",
            "position": "Secrétaire",
            "state": "pending",
            "is_superuser": False,
            "link_sent_at": DjangoJSONEncoder().default(julie.link_sent_at),
        },
        "sent": True,
    }
    [message] = mailoutbox
    assert (message.to, message.subject) == (
        ["julie.petit@example.fr"],
        "Votre accès à l’espace du bureau du Comité des fêtes",
    )
    link = link_of(message)
    assert message.body == (
        "Bonjour Julie,\n"
        "\n"
        "Un compte vous attend dans l’espace du bureau du Comité des fêtes. Choisissez "
        "votre mot de passe pour y entrer.\n"
        "\n"
        "Ce lien est valable 7 jours :\n"
        f"https://site.example/choisir-mot-de-passe#{link['uid']}.{link['token']}\n"
        "\n"
        "Ensuite, connectez-vous depuis cette page :\n"
        "https://site.example/connexion\n"
    )
    assert default_token_generator.check_token(julie, link["token"])


def test_an_invited_member_may_have_no_position(superuser_client):
    response = superuser_client.post(
        ACCOUNTS, invitation(position=None), content_type="application/json"
    )

    assert response.status_code == 201
    assert response.json()["account"]["position"] == ""
    assert User.objects.get(email="julie.petit@example.fr").position == ""


def test_an_invited_member_cannot_sign_in_before_choosing_a_password(superuser_client):
    superuser_client.post(ACCOUNTS, invitation(), content_type="application/json")

    assert not signs_in("julie.petit@example.fr", "")


def test_an_address_already_taken_is_refused_whatever_its_case(superuser_client, mailoutbox):
    """
    Given Julie's account
    When the superuser invites her address again, typed otherwise
    Then it is refused under the address, and no email goes
    """
    UserFactory(email="julie.petit@example.fr")

    response = superuser_client.post(
        ACCOUNTS, invitation(email=" JULIE.PETIT@example.fr "), content_type="application/json"
    )

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "email"],
            "msg": "Un compte existe déjà avec cette adresse.",
        }
    ]
    assert mailoutbox == []


def test_an_invitation_names_its_member_and_gives_a_valid_address(superuser_client):
    """
    Given the superuser
    When they invite an address that is none, without names
    Then each field is refused under itself, all at once
    """
    response = superuser_client.post(
        ACCOUNTS,
        invitation(email="julie", first_name=" ", last_name=""),
        content_type="application/json",
    )

    assert response.status_code == 422
    assert {(tuple(error["loc"]), error["msg"]) for error in response.json()["detail"]} == {
        (("body", "email"), "Saisissez une adresse de courriel valide."),
        (("body", "first_name"), "Ce champ ne peut pas être vide."),
        (("body", "last_name"), "Ce champ ne peut pas être vide."),
    }
    assert not User.objects.filter(email="julie").exists()


def test_a_position_outside_the_list_is_refused(superuser_client):
    response = superuser_client.post(
        ACCOUNTS, invitation(position="Trésorière"), content_type="application/json"
    )

    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [
        ["body", "payload", "position"]
    ]


def test_an_email_that_does_not_go_leaves_the_account_and_is_told(
    superuser_client, mailoutbox, monkeypatch, caplog
):
    """
    Given a mail server that refuses to send
    When the superuser invites Julie
    Then her account is made, without a link sent, the answer says the email
    did not go, and the journal writes why
    """

    def refused(self, messages):
        raise smtplib.SMTPServerDisconnected("Connexion fermée")

    monkeypatch.setattr(EmailBackend, "send_messages", refused)

    response = superuser_client.post(ACCOUNTS, invitation(), content_type="application/json")

    assert response.status_code == 201
    assert (response.json()["sent"], response.json()["account"]["link_sent_at"]) == (False, None)
    assert User.objects.filter(email="julie.petit@example.fr").exists()
    assert "could not be sent" in caplog.text


# The list


def test_the_accounts_are_listed_by_name_with_their_state(superuser_client, superuser):
    """
    Given an account awaiting its password, one active and one deactivated
    When the superuser reads the accounts
    Then each comes by name, with its state, the superuser among them
    """
    pending = UserFactory(first_name="Anne", last_name="Durand")
    pending.set_unusable_password()
    pending.save()
    BoardMemberFactory(first_name="Bruno", last_name="Leroy")
    UserFactory(first_name="Chloé", last_name="Morel", is_active=False)

    response = superuser_client.get(ACCOUNTS)

    assert [(item["first_name"], item["state"]) for item in response.json()["items"]] == [
        ("Anne", AccountState.PENDING),
        ("Bruno", AccountState.ACTIVE),
        ("Chloé", AccountState.INACTIVE),
        ("Gabriel", AccountState.ACTIVE),
    ]
    assert response.json()["items"][1]["position"] == "Trésorier·e"


# A new link


def test_a_new_link_invites_again_a_member_who_awaits_their_password(superuser_client, mailoutbox):
    """
    Given Julie, invited, whose first link was lost
    When the superuser sends her a new link
    Then she receives a second invitation, and either link opens the page
    """
    superuser_client.post(ACCOUNTS, invitation(), content_type="application/json")
    julie = User.objects.get(email="julie.petit@example.fr")

    response = superuser_client.post(f"{ACCOUNTS}/{julie.id}/link")

    assert response.status_code == 200
    assert response.json()["sent"] is True
    first, second = mailoutbox
    assert second.subject == "Votre accès à l’espace du bureau du Comité des fêtes"
    for message in (first, second):
        assert Client().post(
            PASSWORD_LINK, link_of(message), content_type="application/json"
        ).json() == {"email": "julie.petit@example.fr"}


def test_a_password_forgotten_works_until_another_is_chosen(superuser_client, mailoutbox):
    """
    Given Bruno, who has a password and forgot it
    When the superuser sends him a new link
    Then the email offers a new password, his own still working
    And once he chooses another, only the new one signs him in, and the link
    holds no more
    """
    bruno = BoardMemberFactory(first_name="Bruno", email="bruno@example.fr")

    superuser_client.post(f"{ACCOUNTS}/{bruno.id}/link")

    [message] = mailoutbox
    assert message.subject == "Nouveau mot de passe pour l’espace du bureau du Comité des fêtes"
    assert "Votre mot de passe actuel reste valable" in message.body
    assert signs_in("bruno@example.fr", PASSWORD)
    link = link_of(message)
    assert choose(Client(), link).json() == {"email": "bruno@example.fr"}
    assert not signs_in("bruno@example.fr", PASSWORD)
    assert signs_in("bruno@example.fr", NEW_PASSWORD)
    assert choose(Client(), link, "Une-autre-fanfare-2026").json() == invalid_link()


def test_a_deactivated_account_gets_no_link(superuser_client, mailoutbox):
    account = UserFactory(is_active=False)

    response = superuser_client.post(f"{ACCOUNTS}/{account.id}/link")

    assert response.status_code == 422
    assert response.json()["detail"][0]["msg"] == (
        "Ce compte est désactivé : il ne reçoit plus de lien."
    )
    assert mailoutbox == []


def test_a_link_to_an_unknown_account_is_not_found(superuser_client):
    response = superuser_client.post(f"{ACCOUNTS}/999/link")

    assert response.status_code == 404


def test_a_member_without_names_is_greeted_alone(superuser_client, superuser, mailoutbox):
    account = UserFactory(first_name="")

    superuser_client.post(f"{ACCOUNTS}/{account.id}/link")

    assert mailoutbox[0].body.startswith("Bonjour,\n")


# Choosing a password


def test_a_member_chooses_their_password_then_signs_in(superuser_client, mailoutbox, client):
    """
    Given Julie's invitation
    When she opens its link, then chooses her password
    Then the page names her address, and she signs in with her password
    """
    superuser_client.post(ACCOUNTS, invitation(), content_type="application/json")
    link = link_of(mailoutbox[0])

    named = client.post(PASSWORD_LINK, link, content_type="application/json")
    chosen = choose(client, link)

    assert named.json() == chosen.json() == {"email": "julie.petit@example.fr"}
    assert signs_in("julie.petit@example.fr", NEW_PASSWORD)
    assert choose(client, link).json() == invalid_link()


@pytest.mark.parametrize(
    "spoil",
    [
        lambda link: {**link, "token": forged(link["token"])},
        lambda link: {**link, "uid": "MTIzNDU2"},
        lambda link: {**link, "uid": "%%%"},
        lambda link: {**link, "uid": "bm90LWFuLWlk"},
    ],
    ids=["token forged", "unknown account", "malformed", "not an id"],
)
def test_a_link_forged_is_refused(superuser_client, mailoutbox, client, spoil):
    superuser_client.post(ACCOUNTS, invitation(), content_type="application/json")

    response = client.post(
        PASSWORD_LINK, spoil(link_of(mailoutbox[0])), content_type="application/json"
    )

    assert response.status_code == 422
    assert response.json() == invalid_link()


def test_a_link_expired_is_refused(superuser_client, mailoutbox, client, settings):
    """
    Given Julie's invitation, more than seven days old
    When she opens its link
    Then it is refused
    """
    superuser_client.post(ACCOUNTS, invitation(), content_type="application/json")
    settings.PASSWORD_RESET_TIMEOUT = -1

    response = client.post(PASSWORD_LINK, link_of(mailoutbox[0]), content_type="application/json")

    assert response.json() == invalid_link()


def test_the_link_of_an_account_deactivated_since_is_refused(superuser_client, mailoutbox, client):
    superuser_client.post(ACCOUNTS, invitation(), content_type="application/json")
    User.objects.filter(email="julie.petit@example.fr").update(is_active=False)

    assert choose(client, link_of(mailoutbox[0])).json() == invalid_link()


@pytest.mark.parametrize(
    ("password", "confirmation", "errors"),
    [
        (
            "julie2026",
            "julie2026",
            # Django's French puts no-break spaces inside the quotes.
            [("password", "Le mot de passe est trop semblable au champ «\u00a0prénom\u00a0».")],
        ),
        (
            "fanfare",
            "fanfare",
            [
                (
                    "password",
                    "Ce mot de passe est trop court. Il doit contenir au minimum 8 caractères.",
                )
            ],
        ),
        (
            "12345678",
            "12345678",
            [
                ("password", "Ce mot de passe est trop courant."),
                ("password", "Ce mot de passe est entièrement numérique."),
            ],
        ),
        (
            NEW_PASSWORD,
            "Une-autre-fanfare",
            [("confirmation", "Les deux mots de passe ne correspondent pas.")],
        ),
    ],
    ids=["close to the first name", "too short", "common and numeric", "confirmation apart"],
)
def test_a_password_django_refuses_is_told_in_french(
    superuser_client, mailoutbox, client, password, confirmation, errors
):
    superuser_client.post(ACCOUNTS, invitation(), content_type="application/json")

    response = choose(client, link_of(mailoutbox[0]), password, confirmation)

    assert response.status_code == 422
    assert [(error["loc"][-1], error["msg"]) for error in response.json()["detail"]] == errors
    assert not User.objects.get(email="julie.petit@example.fr").has_usable_password()


def test_a_password_is_kept_exactly_as_typed(superuser_client, mailoutbox, client):
    superuser_client.post(ACCOUNTS, invitation(), content_type="application/json")

    choose(client, link_of(mailoutbox[0]), f" {NEW_PASSWORD} ")

    assert signs_in("julie.petit@example.fr", f" {NEW_PASSWORD} ")


def test_choosing_a_password_locks_the_account(superuser_client, mailoutbox):
    """
    Given Julie's invitation
    When her password is recorded
    Then her account is read under a lock: of two sendings of the same link,
    the second waits, then finds its token spent
    """
    superuser_client.post(ACCOUNTS, invitation(), content_type="application/json")
    link = link_of(mailoutbox[0])

    with CaptureQueriesContext(connection) as queries:
        set_password(PasswordIn(**link, password=NEW_PASSWORD, confirmation=NEW_PASSWORD))

    locked = [query["sql"] for query in queries if "FOR UPDATE" in query["sql"]]
    assert len(locked) == 1
    assert '"accounts_user"' in locked[0]


def test_checking_links_is_throttled_after_ten(client):
    for _ in range(10):
        client.post(PASSWORD_LINK, {"uid": "x", "token": "y"}, content_type="application/json")

    response = client.post(
        PASSWORD_LINK, {"uid": "x", "token": "y"}, content_type="application/json"
    )

    assert response.status_code == 429


def test_choosing_a_password_is_throttled_after_five(client):
    link = {"uid": "x", "token": "y"}
    for _ in range(5):
        choose(client, link)

    assert choose(client, link).status_code == 429


# Migration


def test_the_migration_empties_a_position_outside_the_list():
    """
    Given an account whose position was typed before the list was closed, and
    one of the list
    When the migration runs
    Then the first is emptied, the second kept
    """
    typed = BoardMemberFactory()
    User.objects.filter(pk=typed.pk).update(position="Trésorière")
    kept = BoardMemberFactory(position=BoardPosition.PRESIDENT)

    clear_positions_migration.clear_unknown_positions(apps, None)

    typed.refresh_from_db()
    kept.refresh_from_db()
    assert (typed.position, kept.position) == ("", BoardPosition.PRESIDENT)
