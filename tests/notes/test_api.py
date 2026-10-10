import datetime as dt

import pytest
from django.core.serializers.json import DjangoJSONEncoder
from django.test import Client
from django.utils import timezone
from ninja_jwt.tokens import AccessToken

from notes.models import Note
from tests.accounts.factories import BoardMemberFactory, UserFactory
from tests.events.factories import EventFactory
from tests.notes.factories import NoteFactory, ReplyFactory

pytestmark = pytest.mark.django_db

NOTES = "/api/board/notes"

# Every operation on the notes, the paths of a single note naming any id: a
# refusal comes before the note is looked up.
OPERATIONS = [
    ("get", f"{NOTES}?event=1"),
    ("post", NOTES),
    ("put", f"{NOTES}/1"),
    ("delete", f"{NOTES}/1"),
    ("post", f"{NOTES}/1/replies"),
]


def note_url(note_id):
    return f"{NOTES}/{note_id}"


def replies_url(note_id):
    return f"{NOTES}/{note_id}/replies"


def send(client, method, path, payload=None):
    return getattr(client, method)(path, payload, content_type="application/json")


def iso(moment):
    """A time as the API writes it: to the millisecond, as Django's JSON does."""
    return DjangoJSONEncoder().default(moment)


def member_json(member):
    return {
        "id": member.id,
        "first_name": member.first_name,
        "last_name": member.last_name,
        "email": member.email,
    }


def client_of(member):
    return Client(headers={"Authorization": f"Bearer {AccessToken.for_user(member)}"})


def listed_texts(client, event):
    return [note["text"] for note in client.get(NOTES, {"event": event.id}).json()["items"]]


def written_at(note, moment):
    """Date a note, its creation time being set by the database."""
    Note.objects.filter(pk=note.pk).update(created_at=moment)


def note_payload(event, **changes):
    """The JSON body of a note, as the event's tab sends it."""
    return {
        "event": event.id,
        "text": "Clés à récupérer en mairie.",
        "tag": None,
        "pinned": False,
    } | changes


# Access


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_notes_are_reserved_to_signed_in_members(client, method, path):
    """
    Given a visitor without a session
    When they call any operation on the notes
    Then they are refused with a 401
    """
    assert getattr(client, method)(path).status_code == 401


@pytest.mark.parametrize(("method", "path"), OPERATIONS)
def test_notes_are_refused_to_accounts_outside_the_board(method, path):
    """
    Given an account outside the board, signed in
    When it calls any operation on the notes
    Then it is refused with a 403
    """
    assert getattr(client_of(UserFactory()), method)(path).status_code == 403


# List


def test_the_notes_of_an_event_come_pinned_first_then_the_latest(board_client):
    """
    Given an event with three notes, the oldest one pinned, a note on another
    event and a general note
    When the board lists the event's notes
    Then the pinned note comes first, then the latest, the others left out
    """
    halloween = EventFactory()
    now = timezone.now()
    for text, days_ago, pinned in [
        ("Contacts utiles", 30, True),
        ("Budget bonbons", 8, False),
        ("Parcours validé", 2, False),
    ]:
        written_at(
            NoteFactory(event=halloween, text=text, pinned=pinned), now - dt.timedelta(days_ago)
        )
    NoteFactory(text="Lots du loto")
    NoteFactory(event=None, text="Liste de courses")

    assert listed_texts(board_client, halloween) == [
        "Contacts utiles",
        "Parcours validé",
        "Budget bonbons",
    ]


def test_notes_written_together_come_the_last_recorded_first(board_client):
    """
    Given two notes of an event written at the same time
    When the board lists the event's notes
    Then the one recorded last comes first
    """
    event = EventFactory()
    moment = timezone.now()
    for text in ["Premier", "Second"]:
        written_at(NoteFactory(event=event, text=text), moment)

    assert listed_texts(board_client, event) == ["Second", "Premier"]


def test_a_listed_note_holds_its_author_tag_pin_and_replies(board_client, board_member):
    """
    Given a pinned budget note of the signed-in member, answered by two other
    members in turn
    When the member lists the event's notes
    Then the note comes with its author, text, dates, tag and pin, and says the
    member may change it
    And its replies follow in the order they were written, with their authors,
    neither of them changeable by the member
    """
    note = NoteFactory(author=board_member, tag="budget", pinned=True, text="250 € au plus.")
    julie = BoardMemberFactory(first_name="Julie", last_name="Roux")
    marc = BoardMemberFactory(first_name="Marc", last_name="Dubois")
    first = ReplyFactory(parent=note, author=julie, text="D’accord.")
    second = ReplyFactory(parent=note, author=marc, text="Je passe commande.")
    written_at(second, first.created_at + dt.timedelta(minutes=5))
    note.refresh_from_db()
    first.refresh_from_db()
    second.refresh_from_db()

    assert board_client.get(NOTES, {"event": note.event_id}).json() == {
        "items": [
            {
                "id": note.id,
                "author": member_json(board_member),
                "text": "250 € au plus.",
                "created_at": iso(note.created_at),
                "updated_at": iso(note.updated_at),
                "editable": True,
                "tag": "budget",
                "pinned": True,
                "replies": [
                    {
                        "id": reply.id,
                        "author": member_json(author),
                        "text": reply.text,
                        "created_at": iso(reply.created_at),
                        "updated_at": iso(reply.updated_at),
                        "editable": False,
                    }
                    for reply, author in [(first, julie), (second, marc)]
                ],
            }
        ],
        "count": 1,
    }


def test_a_member_may_change_their_own_replies_only(board_client, board_member):
    """
    Given a note of another member, answered by the signed-in member, then by
    the note's author
    When the member lists the event's notes
    Then the note is not theirs to change, their reply is, the other is not
    """
    note = NoteFactory()
    ReplyFactory(parent=note, author=board_member)
    ReplyFactory(parent=note, author=note.author)

    listed = board_client.get(NOTES, {"event": note.event_id}).json()["items"][0]

    assert listed["editable"] is False
    assert [reply["editable"] for reply in listed["replies"]] == [True, False]


def test_a_note_whose_author_was_deleted_is_listed_without_a_name(board_client):
    """
    Given a note and its reply whose authors' accounts were deleted
    When the board lists the event's notes
    Then both come without an author, and nobody may change them
    """
    reply = ReplyFactory()
    reply.author.delete()
    reply.parent.author.delete()

    listed = board_client.get(NOTES, {"event": reply.parent.event_id}).json()["items"][0]

    assert (listed["author"], listed["editable"]) == (None, False)
    assert (listed["replies"][0]["author"], listed["replies"][0]["editable"]) == (None, False)


def test_the_notes_come_by_page(board_client):
    """
    Given an event with three notes
    When the board lists them by pages of two
    Then the first page holds two notes, and the count tells there are three
    """
    event = EventFactory()
    NoteFactory.create_batch(3, event=event)

    body = board_client.get(NOTES, {"event": event.id, "page_size": 2}).json()

    assert (len(body["items"]), body["count"]) == (2, 3)


def test_listing_the_notes_reads_their_authors_and_replies_at_once(
    board_client, django_assert_max_num_queries
):
    """
    Given an event with five notes, each answered twice
    When the board lists the event's notes
    Then the notes, their authors and their replies take a fixed number of queries
    """
    event = EventFactory()
    for note in NoteFactory.create_batch(5, event=event):
        ReplyFactory.create_batch(2, parent=note)

    # Authentication (2), count and page of notes, replies with their authors.
    with django_assert_max_num_queries(5):
        response = board_client.get(NOTES, {"event": event.id})

    assert len(response.json()["items"]) == 5


def test_the_notes_are_listed_for_an_event_only(board_client):
    """
    Given the board's notes
    When they are listed without naming an event
    Then the request is refused with a 422, located under the missing event
    """
    response = board_client.get(NOTES)

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {"type": "missing", "loc": ["query", "event"], "msg": "Ce champ est obligatoire."}
    ]


# Writing


def test_a_member_writes_a_note_on_an_event(board_client, board_member):
    """
    Given an event
    When a member writes a logistics note on it
    Then the note is recorded with the member as its author
    And the answer shows it as the event's tab does, changeable by the member
    """
    event = EventFactory()

    response = send(
        board_client, "post", NOTES, note_payload(event, tag="logistics", text="  Salle réservée. ")
    )

    assert response.status_code == 201
    note = Note.objects.get()
    assert (note.event, note.author, note.text, note.tag) == (
        event,
        board_member,
        "Salle réservée.",
        "logistics",
    )
    assert response.json() == {
        "id": note.id,
        "author": member_json(board_member),
        "text": "Salle réservée.",
        "created_at": iso(note.created_at),
        "updated_at": iso(note.updated_at),
        "editable": True,
        "tag": "logistics",
        "pinned": False,
        "replies": [],
    }


def test_a_member_writes_a_general_note(board_client):
    """
    Given no event to attach it to
    When a member writes a note without event
    Then the note is recorded as a general note
    """
    response = send(
        board_client,
        "post",
        NOTES,
        {"event": None, "text": "Assemblée générale en janvier.", "tag": None, "pinned": False},
    )

    assert response.status_code == 201
    assert Note.objects.get().event is None


def test_an_empty_note_is_refused_under_its_text(board_client):
    """
    Given an event
    When a member publishes a note made of spaces only
    Then the note is refused with a 422, located under its text
    """
    response = send(board_client, "post", NOTES, note_payload(EventFactory(), text="   "))

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "text"],
            "msg": "Ce champ ne peut pas être vide.",
        }
    ]
    assert not Note.objects.exists()


def test_a_note_on_an_unknown_event_is_refused_under_its_event(board_client):
    """
    Given no event of id 987654
    When a member writes a note on it
    Then the note is refused with a 422, located under its event
    """
    payload = {"event": 987654, "text": "Note.", "tag": None, "pinned": False}

    response = send(board_client, "post", NOTES, payload)

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body", "event"],
            "msg": "Choisissez un événement existant.",
        }
    ]


def test_an_unknown_tag_is_refused_in_french(board_client):
    """
    Given an event
    When a member sends a note with a tag the board does not know
    Then the note is refused with a 422, in French, located under its tag
    """
    response = send(board_client, "post", NOTES, note_payload(EventFactory(), tag="divers"))

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "enum",
            "loc": ["body", "payload", "tag"],
            "msg": "Sélectionnez un choix valide. Ce choix ne fait pas partie de ceux disponibles.",
        }
    ]


# Rewriting and deleting


def test_the_author_rewrites_and_pins_their_note(board_client, board_member):
    """
    Given a note of the signed-in member
    When the member rewrites its text, tags it and pins it
    Then the note is saved, and the answer shows it as rewritten
    """
    note = NoteFactory(author=board_member)

    response = send(
        board_client,
        "put",
        note_url(note.id),
        {"text": "Salle réservée de 14 h à 20 h.", "tag": "logistics", "pinned": True},
    )

    assert response.status_code == 200
    note.refresh_from_db()
    assert (note.text, note.tag, note.pinned) == (
        "Salle réservée de 14 h à 20 h.",
        "logistics",
        True,
    )
    assert response.json()["text"] == "Salle réservée de 14 h à 20 h."


@pytest.mark.parametrize("target", ["note", "reply"])
def test_only_its_author_finds_a_note_or_a_reply_to_change(board_client, target):
    """
    Given a note answered once, both written by other members
    When the signed-in member rewrites or deletes the note or the reply
    Then neither is found, with a 404, and both stay as they were
    """
    reply = ReplyFactory()
    note = {"note": reply.parent, "reply": reply}[target]
    original = note.text

    rewrite = send(
        board_client, "put", note_url(note.id), {"text": "Autre", "tag": None, "pinned": False}
    )
    deletion = board_client.delete(note_url(note.id))

    assert (rewrite.status_code, deletion.status_code) == (404, 404)
    assert deletion.json() == {"detail": "Introuvable."}
    note.refresh_from_db()
    assert note.text == original


def test_the_author_of_a_reply_rewrites_it(board_client, board_member):
    """
    Given the signed-in member's reply to another member's note
    When the member rewrites the reply
    Then the reply is saved, with neither tag nor pin
    """
    reply = ReplyFactory(author=board_member)

    response = send(
        board_client,
        "put",
        note_url(reply.id),
        {"text": "C’est fait.", "tag": None, "pinned": False},
    )

    assert response.status_code == 200
    assert response.json()["replies"] == []
    reply.refresh_from_db()
    assert reply.text == "C’est fait."


@pytest.mark.parametrize("change", [{"tag": "budget"}, {"pinned": True}], ids=["tag", "pin"])
def test_a_reply_cannot_be_tagged_or_pinned(board_client, board_member, change):
    """
    Given the signed-in member's reply
    When the member tags it or pins it
    Then the change is refused with a 422, about the whole reply
    """
    reply = ReplyFactory(author=board_member)

    response = send(
        board_client,
        "put",
        note_url(reply.id),
        {"text": reply.text, "tag": None, "pinned": False} | change,
    )

    assert response.status_code == 422
    assert response.json()["detail"] == [
        {
            "type": "validation_error",
            "loc": ["body"],
            "msg": "Une réponse n’a ni événement, ni étiquette, ni épingle.",
        }
    ]


def test_the_author_deletes_a_note_with_its_replies(board_client, board_member):
    """
    Given a note of the signed-in member, answered by another member
    When the member deletes the note
    Then the note and its reply are deleted
    """
    reply = ReplyFactory(parent=NoteFactory(author=board_member))

    response = board_client.delete(note_url(reply.parent_id))

    assert response.status_code == 204
    assert not Note.objects.exists()


def test_the_author_of_a_reply_deletes_it_alone(board_client, board_member):
    """
    Given the signed-in member's reply to another member's note
    When the member deletes the reply
    Then the reply is deleted, and the note stays
    """
    reply = ReplyFactory(author=board_member)

    response = board_client.delete(note_url(reply.id))

    assert response.status_code == 204
    assert list(Note.objects.all()) == [reply.parent]


# Replies


def test_a_member_replies_to_another_members_note(board_client, board_member):
    """
    Given another member's note on an event
    When the signed-in member replies to it
    Then the reply is recorded under the note, by the member, without event
    And the answer shows it as the note's replies do
    """
    note = NoteFactory()

    response = send(board_client, "post", replies_url(note.id), {"text": " Je m’en occupe. "})

    assert response.status_code == 201
    reply = note.replies.get()
    assert (reply.author, reply.text, reply.event) == (board_member, "Je m’en occupe.", None)
    assert response.json() == {
        "id": reply.id,
        "author": member_json(board_member),
        "text": "Je m’en occupe.",
        "created_at": iso(reply.created_at),
        "updated_at": iso(reply.updated_at),
        "editable": True,
    }


def test_a_reply_cannot_be_answered(board_client):
    """
    Given a reply to a note
    When a member replies to the reply
    Then the reply is not found as a note to answer, with a 404
    """
    reply = ReplyFactory()

    response = send(board_client, "post", replies_url(reply.id), {"text": "Moi aussi."})

    assert response.status_code == 404
    assert not reply.replies.exists()


def test_an_empty_reply_is_refused_under_its_text(board_client):
    """
    Given a note
    When a member sends an empty reply
    Then the reply is refused with a 422, located under its text
    """
    response = send(board_client, "post", replies_url(NoteFactory().id), {"text": ""})

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "text"]


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("put", note_url(987654), {"text": "Note.", "tag": None, "pinned": False}),
        ("delete", note_url(987654), None),
        ("post", replies_url(987654), {"text": "Réponse."}),
    ],
)
def test_an_unknown_note_is_not_found(board_client, method, path, payload):
    """
    Given no note of id 987654
    When a member rewrites it, deletes it or replies to it
    Then the answer is a 404, in French
    """
    response = send(board_client, method, path, payload)

    assert response.status_code == 404
    assert response.json() == {"detail": "Introuvable."}
