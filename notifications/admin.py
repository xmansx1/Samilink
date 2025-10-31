from django.contrib import admin
from .models import Notification

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """
    Admin مرن لا يفترض أسماء حقول ثابتة.
    - يعرض: id, المستخدم, العنوان, مقروء؟, تاريخ الإنشاء
    - يبحث في: العنوان/النص/إيميل واسم المستخدم (إن وُجدت العلاقات)
    - الفلاتر تُحدد ديناميكياً حسب الحقول الموجودة (created_at/created/timestamp)
    """

    list_display = ("id", "_user", "_title", "_is_read", "_created_at")
    ordering = ("-id",)
    # لا نعرّف list_filter هنا إطلاقًا — get_list_filter ستُرجع الحقول الفعلية
    search_fields = (
        "title",
        "body",
        "user__email", "user__username", "user__name",
        "recipient__email", "recipient__username", "recipient__name",
        "owner__email", "owner__username", "owner__name",
    )

    # ---- أعمدة مرنة للعرض ----
    def _user(self, obj):
        return getattr(obj, "user", None) or getattr(obj, "recipient", None) or getattr(obj, "owner", None) or "-"
    _user.short_description = "المستخدم"

    def _title(self, obj):
        return getattr(obj, "title", None) or str(obj)
    _title.short_description = "العنوان"

    def _is_read(self, obj):
        if hasattr(obj, "is_read"):
            return bool(getattr(obj, "is_read"))
        if hasattr(obj, "read"):
            return bool(getattr(obj, "read"))
        if hasattr(obj, "seen"):
            return bool(getattr(obj, "seen"))
        return False
    _is_read.boolean = True
    _is_read.short_description = "مقروء؟"

    def _created_at(self, obj):
        for name in ("created_at", "created", "timestamp"):
            if hasattr(obj, name):
                return getattr(obj, name)
        return None
    _created_at.admin_order_field = "created_at"
    _created_at.short_description = "تاريخ الإنشاء"

    # ---- فلاتر القائمة: نرجّع الحقل الزمني الحقيقي فقط إن وُجد ----
    def get_list_filter(self, request):
        for name in ("created_at", "created", "timestamp"):
            try:
                Notification._meta.get_field(name)
                return (name,)
            except Exception:
                continue
        return tuple()
