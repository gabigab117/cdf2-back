from django.apps import AppConfig
from pillow_heif import register_heif_opener


class DocumentsConfig(AppConfig):
    name = "documents"
    verbose_name = "Documents"

    def ready(self):
        # Pillow opens the HEIC photos of an iPhone once this plugin is
        # registered: they are converted to WebP like any other photo (D9).
        register_heif_opener()
