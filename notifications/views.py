from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

# استيراد الموديل
from .models import Notification


# =========================
# Helpers دفاعية للحقول
# =========================
def _user_field_candidates():
    # أسماء محتملة لعلاقة المستخدم
    return ["user", "recipient", "owner", "account", "to_user"]

def _is_read_field_candidates():
    # فلاغ المقروء
    return ["is_read", "read", "seen", "is_seen", "has_read"]

def _created_field_candidates():
    # تاريخ/توقيت الإنشاء
    return ["created_at", "created", "timestamp", "date_created", "inserted_at"]

def _pick_model_field_only(candidates):
    """اختر أول اسم حقل موجود على الموديل (Model _meta)."""
    fields = set(f.name for f in Notification._meta.get_fields())
    for c in candidates:
        if c in fields:
            return c
    return None

def _column_exists(col_name):
    """تحقق من وجود عمود حقيقي بهذا الاسم في جدول الإشعارات (SQLite/Postgres…)."""
    try:
        with connection.cursor() as cur:
            table = Notification._meta.db_table
            cur.execute(f"PRAGMA table_info({table})")  # يعمل مع SQLite؛ في Postgres سيُتجاهَل دون كسر
            rows = cur.fetchall()
        # rows: [(cid, name, type, notnull, dflt_value, pk), ...]
        names = {r[1] for r in rows} if rows else set()
        return col_name in names if names else True  # لو ما قدر يحصلها، لا نمنع التنفيذ
    except Exception:
        return True

def _pick_existing_db_field(candidates):
    """
    اختر أول حقل Model موجود وله عمود فعلي في قاعدة البيانات (لتفادي OperationalError).
    """
    for c in candidates:
        if _pick_model_field_only([c]) and _column_exists(c):
            return c
    return None


# =========================
# API خفيفة للجرس في الهيدر
# =========================
@login_required
@require_GET
def api_unread_count(request):
    uf = _pick_existing_db_field(_user_field_candidates())
    rf = _pick_existing_db_field(_is_read_field_candidates())
    if not uf or not rf:
        return JsonResponse({"count": 0})
    qs = Notification.objects.filter(**{uf: request.user, rf: False})
    return JsonResponse({"count": qs.count()})

@login_required
@require_GET
def api_list(request):
    uf = _pick_existing_db_field(_user_field_candidates())
    rf = _pick_existing_db_field(_is_read_field_candidates())
    cf = _pick_existing_db_field(_created_field_candidates()) or "id"

    if not uf:
        return JsonResponse({"results": []})

    limit = int(request.GET.get("limit", "10"))
    limit = 5 if limit < 5 else (50 if limit > 50 else limit)

    qs = (Notification.objects
          .filter(**{uf: request.user})
          .order_by(f"-{cf}")[:limit])

    data = []
    for n in qs:
        data.append({
            "id": n.pk,
            "title": getattr(n, "title", "") or str(n),
            "body": getattr(n, "body", "") or "",
            "url": getattr(n, "url", "") or "",
            "is_read": bool(getattr(n, rf, False)) if rf else False,
            "created_at": getattr(n, cf, None) if cf else None,
        })
    return JsonResponse({"results": data})

@login_required
@require_POST
def api_mark_read(request):
    nid = request.POST.get("id")
    if not nid:
        return HttpResponseBadRequest("missing id")
    uf = _pick_existing_db_field(_user_field_candidates())
    rf = _pick_existing_db_field(_is_read_field_candidates())
    if not uf or not rf:
        return JsonResponse({"ok": False})

    obj = get_object_or_404(Notification, pk=nid, **{uf: request.user})
    setattr(obj, rf, True)
    obj.save(update_fields=[rf])
    return JsonResponse({"ok": True})

@login_required
@require_POST
def api_mark_all_read(request):
    uf = _pick_existing_db_field(_user_field_candidates())
    rf = _pick_existing_db_field(_is_read_field_candidates())
    if not uf or not rf:
        return JsonResponse({"ok": False})
    Notification.objects.filter(**{uf: request.user, rf: False}).update(**{rf: True})
    return JsonResponse({"ok": True})


# =========================
# صفحات HTML جميلة وقابلة للاستخدام
# =========================
@login_required
def page_index(request):
    """
    صفحة الإشعارات مع:
    - تبويب: الكل / غير مقروء عبر only=unread
    - بحث نصّي q
    - ترقيم صفحات page/per
    """
    uf = _pick_existing_db_field(_user_field_candidates())
    rf = _pick_existing_db_field(_is_read_field_candidates())
    cf = _pick_existing_db_field(_created_field_candidates()) or "id"

    qs = Notification.objects.all()
    if uf:
        qs = qs.filter(**{uf: request.user})

    # فلترة غير مقروء
    only = (request.GET.get("only") or "").strip()
    if only == "unread" and rf:
        qs = qs.filter(**{rf: False})

    # بحث بسيط في العنوان/المتن إن وُجدت الحقول
    q = (request.GET.get("q") or "").strip()
    if q:
        from django.db.models import Q
        q_expr = Q()
        if _pick_model_field_only(["title"]):
            q_expr |= Q(title__icontains=q)
        if _pick_model_field_only(["body"]):
            q_expr |= Q(body__icontains=q)
        if q_expr:
            qs = qs.filter(q_expr)

    qs = qs.order_by(f"-{cf}")

    # ترقيم
    try:
        page = max(1, int(request.GET.get("page", "1")))
    except Exception:
        page = 1
    try:
        per = int(request.GET.get("per", "10"))
        per = 5 if per < 5 else (50 if per > 50 else per)
    except Exception:
        per = 10

    total = qs.count()
    start = (page - 1) * per
    end = start + per
    rows = list(qs[start:end])

    # أسماء الحقول للعرض
    rf_model = _pick_model_field_only(_is_read_field_candidates())
    cf_model = _pick_model_field_only(_created_field_candidates())

    items = []
    for n in rows:
        items.append({
            "obj": n,
            "id": n.pk,
            "title": getattr(n, "title", "") or str(n),
            "body": getattr(n, "body", "") or "",
            "url": getattr(n, "url", "") or "",
            "is_read": bool(getattr(n, rf_model, False)) if rf_model else False,
            "created_at": getattr(n, cf_model, None) if cf_model else None,
        })

    ctx = {
        "items": items,
        "page": page,
        "per": per,
        "total": total,
        "has_prev": page > 1,
        "has_next": end < total,
        "prev_page": page - 1,
        "next_page": page + 1,
        "only": only,
        "q": q,
    }
    return render(request, "notifications/index.html", ctx)


@login_required
@require_POST
def page_mark_read(request, pk: int):
    uf = _pick_existing_db_field(_user_field_candidates())
    rf = _pick_existing_db_field(_is_read_field_candidates())
    if not uf or not rf:
        messages.error(request, "لا يمكن تعديل حالة الإشعار حالياً.")
        return redirect("notifications:index")

    obj = get_object_or_404(Notification, pk=pk, **{uf: request.user})
    setattr(obj, rf, True)
    obj.save(update_fields=[rf])
    messages.success(request, "تم تعليم الإشعار كمقروء.")
    return redirect("notifications:index")


@login_required
@require_POST
def page_mark_all_read(request):
    uf = _pick_existing_db_field(_user_field_candidates())
    rf = _pick_existing_db_field(_is_read_field_candidates())
    if not uf or not rf:
        messages.error(request, "لا يمكن تعديل حالة الإشعارات حالياً.")
        return redirect("notifications:index")

    Notification.objects.filter(**{uf: request.user, rf: False}).update(**{rf: True})
    messages.success(request, "تم تعليم كل الإشعارات كمقروءة.")
    return redirect("notifications:index")


@login_required
@require_POST
def page_delete(request, pk: int):
    uf = _pick_existing_db_field(_user_field_candidates())
    if not uf:
        messages.error(request, "لا يمكن حذف الإشعار حالياً.")
        return redirect("notifications:index")

    obj = get_object_or_404(Notification, pk=pk, **{uf: request.user})
    obj.delete()
    messages.success(request, "تم حذف الإشعار.")
    return redirect("notifications:index")


@login_required
@require_POST
def page_delete_all_read(request):
    uf = _pick_existing_db_field(_user_field_candidates())
    rf = _pick_existing_db_field(_is_read_field_candidates())
    if not uf or not rf:
        messages.error(request, "لا يمكن حذف الإشعارات حالياً.")
        return redirect("notifications:index")

    Notification.objects.filter(**{uf: request.user, rf: True}).delete()
    messages.success(request, "تم حذف جميع الإشعارات المقروءة.")
    return redirect("notifications:index")
