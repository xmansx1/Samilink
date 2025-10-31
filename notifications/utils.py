from .models import Notification

def create_notification(user, title, body="", url=""):
    """
    أداة إنشاء إشعار متوافقة مع ما استدعيتَه في الـ views:
      from notifications.utils import create_notification
    لا تفترض وجود level أو غيره.
    """
    try:
        kwargs = {}
        # اسم الحقل الخاص بالمستخدم قد يختلف:
        user_field = None
        for name in ("user", "recipient", "owner"):
            try:
                Notification._meta.get_field(name)
                user_field = name
                break
            except Exception:
                continue
        if not user_field:
            return None

        kwargs[user_field] = user
        if hasattr(Notification, "title"):
            kwargs["title"] = title or ""
        if hasattr(Notification, "body"):
            kwargs["body"] = body or ""
        if hasattr(Notification, "url"):
            kwargs["url"] = url or ""

        return Notification.objects.create(**kwargs)
    except Exception:
        return None
