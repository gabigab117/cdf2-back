import uuid

from django.conf import settings
from django.db import models

from events.models import EVENT_ERROR_MESSAGES, Event


def photo_path(photo, filename):
    # The name on disk tells nothing of the photo: a random UUID. Every size of
    # every photo lives under photos/, which nginx marks as not to be indexed
    # (D17).
    return f"photos/{uuid.uuid4()}.webp"


class Album(models.Model):
    """An album of photos, of an event or of the committee's life: private until a
    member publishes it (D17).
    """

    title = models.CharField("titre", max_length=120)
    date = models.DateField("date")
    # An album outlives its event.
    event = models.ForeignKey(
        Event,
        verbose_name="événement",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="albums",
        error_messages=EVENT_ERROR_MESSAGES,
    )
    published = models.BooleanField("publié", default=False)
    cover = models.ForeignKey(
        "Photo",
        verbose_name="couverture",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField("créé le", auto_now_add=True)

    class Meta:
        verbose_name = "album"

    def __str__(self):
        return self.title


class Photo(models.Model):
    """A photo of an album, re-encoded without its metadata (D9), in three sizes:
    the image, the display of the viewer and the thumbnail of the grid.
    """

    album = models.ForeignKey(
        Album, verbose_name="album", on_delete=models.CASCADE, related_name="photos"
    )
    image = models.FileField("image", upload_to=photo_path)
    display = models.FileField("affichage", upload_to=photo_path)
    thumbnail = models.FileField("vignette", upload_to=photo_path)
    original_name = models.CharField("nom d’origine", max_length=255)
    # The fingerprint of the bytes the member sent: the same file twice in an
    # album is the same photo.
    sha256 = models.CharField("empreinte", max_length=64)
    # Of the image, once upright.
    width = models.PositiveIntegerField("largeur")
    height = models.PositiveIntegerField("hauteur")
    # When the camera took it, if it recorded it.
    taken_at = models.DateTimeField("prise le", null=True, blank=True)
    hidden = models.BooleanField("masquée du site", default=False)
    # Set on a photo whose image rights are in doubt: it is not published until
    # a member clears it (D17).
    image_rights_to_review = models.BooleanField("droit à l’image à vérifier", default=False)
    # A deleted account leaves its photos behind, without a name.
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        verbose_name="ajoutée par",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_photos",
    )
    created_at = models.DateTimeField("ajoutée le", auto_now_add=True)

    class Meta:
        verbose_name = "photo"
        constraints = [
            models.UniqueConstraint(
                fields=["album", "sha256"],
                name="photo_unique_sha256_in_album",
                violation_error_message="Cette photo est déjà dans l’album.",
            ),
        ]

    def __str__(self):
        return self.original_name
