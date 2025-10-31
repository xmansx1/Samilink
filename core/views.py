from urllib.parse import quote
from django.contrib.auth import get_user_model
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect

User = get_user_model()

def whatsapp_redirect_user(request, user_id: int):
    """
    Proxy عام لإخفاء أرقام المستخدمين عند إنشاء رابط واتساب.
    Rate-limit بسيط بالجلسة (5 ثواني).
    """
    user = get_object_or_404(User, pk=user_id, is_active=True)
    if not user.phone:
        return HttpResponseBadRequest("لا يتوفر رقم جوال.")

    import time
    key = f"wa_last_user_{user_id}"
    last = request.session.get(key, 0.0)
    now = time.time()
    if now - last < 5:
        pass
    request.session[key] = now

    msg = (request.GET.get("msg") or "").strip()[:200]
    q = f"?text={quote(msg)}" if msg else ""
    number = user.phone[1:] if user.phone.startswith("+") else user.phone
    return redirect(f"https://wa.me/{number}{q}")
