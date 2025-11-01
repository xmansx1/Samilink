# finance/apps.py
from __future__ import annotations

import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "finance"
    verbose_name = "المالية"
