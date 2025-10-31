# accounts/backends.py
from __future__ import annotations

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()

class EmailBackend(ModelBackend):
    """
    مصادقة بالبريد الإلكتروني فقط.
    - يتعامل مع email kwarg بشكل أساسي.
    - يدعم username كبديل للمشاريع القديمة (Backward Compatible).
    - المقارنة غير حساسة لحالة الأحرف (email__iexact).
    """

    def authenticate(self, request, username=None, password=None, email=None, **kwargs):
        # قبول email أو username (للتوافق الخلفي) ثم تطبيع
        login_email = (email or username or kwargs.get("email") or "").strip().lower()
        if not login_email or not password:
            return None

        try:
            user = User.objects.get(email__iexact=login_email)
        except User.DoesNotExist:
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
