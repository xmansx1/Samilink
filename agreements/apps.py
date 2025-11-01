# agreements/apps.py
from django.apps import AppConfig

class AgreementsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "agreements"

    def ready(self):
        # مهم: تحميل الإشارات
        import agreements.signals  # noqa: F401
