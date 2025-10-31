from django.apps import AppConfig

class MarketplaceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "marketplace"
    verbose_name = "السوق (طلبات وعروض)"

    def ready(self):
        from . import signals  # noqa
