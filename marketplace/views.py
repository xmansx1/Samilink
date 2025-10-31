# marketplace/views.py
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import Q, Prefetch
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView

from notifications.utils import create_notification

from .forms import RequestCreateForm, OfferCreateForm, OfferForm, AdminReassignForm
from .models import Request, Offer, Note

# (اختياري) نظام إشعارات قديم — أبقيناه لتوافق خلفي، لكن لن نعتمد عليه
try:
    from core.models import Notification as LegacyNotificationModel  # noqa
except Exception:
    LegacyNotificationModel = None  # noqa


# -----------------------
# Mixins للصلاحيات
# -----------------------
class ClientOnlyMixin(UserPassesTestMixin):
    """يسمح فقط للمستخدم بدور عميل."""
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and getattr(u, "role", None) == "client"


class EmployeeOnlyMixin(UserPassesTestMixin):
    """يسمح فقط للمستخدم بدور موظف."""
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and getattr(u, "role", None) == "employee"


# -----------------------
# أدوات إشعار احترافية (تُحافظ على التوافق مع الاستدعاءات القديمة)
# -----------------------
def _send_email_safely(subject: str, body: str, to_email: str):
    try:
        if getattr(settings, "DEFAULT_FROM_EMAIL", None) and to_email:
            send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [to_email], fail_silently=True)
    except Exception:
        pass


def _notify(recipient, title: str, body: str = ""):
    """
    واجهة قديمة مُحتفَظ بها — الآن تُنشئ تنبيه داخل المنصّة، وتُحاول إرسال بريد اختياريًا.
    """
    try:
        create_notification(recipient=recipient, title=title, body=body, url="")
    except Exception:
        pass
    _send_email_safely(title, body, getattr(recipient, "email", None))


def _notify_link(recipient, title: str, body: str = "", url: str = "", actor=None, target=None):
    """
    واجهة موسعة تدعم الرابط والفاعل والهدف (للاستخدام داخل الأكواد الجديدة).
    """
    try:
        create_notification(recipient=recipient, title=title, body=body, url=url or "", actor=actor, target=target)
    except Exception:
        pass
    _send_email_safely(title, body, getattr(recipient, "email", None))


def _notify_new_offer(off: Offer):
    _notify_link(
        recipient=off.request.client,
        title="عرض جديد على طلبك",
        body=f"قدّم {off.employee} عرضًا بقيمة {off.proposed_price} لمدة {off.proposed_duration_days} يوم.",
        url=reverse("marketplace:request_detail", args=[off.request_id]),
        actor=off.employee,
        target=off.request,
    )


def _notify_offer_selected(off: Offer):
    _notify_link(
        recipient=off.employee,
        title="تم اختيار عرضك",
        body=f"تم اختيار عرضك لطلب [{off.request_id}] {off.request.title}.",
        url=reverse("marketplace:request_detail", args=[off.request_id]),
        actor=off.request.client,
        target=off.request,
    )


# -----------------------
# الطلبات
# -----------------------
class RequestCreateView(LoginRequiredMixin, ClientOnlyMixin, CreateView):
    """إنشاء طلب جديد بواسطة العميل."""
    template_name = "marketplace/request_create.html"
    model = Request
    form_class = RequestCreateForm

    def form_valid(self, form):
        form.instance.client = self.request.user
        self.object = form.save()
        messages.success(self.request, "تم إنشاء الطلب بنجاح.")
        # تنبيه تأكيد للعميل (اختياري لكنه لطيف)
        try:
            _notify_link(
                recipient=self.request.user,
                title="تم إنشاء طلبك",
                body=f"تم إنشاء الطلب #{self.object.pk}: {self.object.title}",
                url=reverse("marketplace:request_detail", args=[self.object.pk]),
                actor=self.request.user,
                target=self.object,
            )
        except Exception:
            pass
        return redirect("marketplace:request_detail", pk=self.object.pk)

    def form_invalid(self, form):
        messages.error(self.request, "لم يتم إنشاء الطلب. الرجاء تصحيح الأخطاء.")
        return super().form_invalid(form)


class MyRequestsListView(LoginRequiredMixin, ClientOnlyMixin, ListView):
    """قائمة طلبات العميل الحالي."""
    template_name = "marketplace/my_requests.html"
    context_object_name = "requests"
    paginate_by = 10

    def get_queryset(self):
        return (
            Request.objects
            .filter(client=self.request.user)
            .select_related("client", "assigned_employee")
            .order_by("-created_at")
        )


class NewRequestsForEmployeesView(LoginRequiredMixin, EmployeeOnlyMixin, ListView):
    """الطلبات الجديدة المتاحة للعروض (غير المسندة)."""
    template_name = "marketplace/new_requests.html"
    context_object_name = "requests"
    paginate_by = 10

    def get_queryset(self):
        return (
            Request.objects
            .filter(status=Request.Status.NEW, assigned_employee__isnull=True)
            .select_related("client")
            .order_by("-created_at")
        )


class RequestDetailView(LoginRequiredMixin, DetailView):
    """
    تفاصيل الطلب مع احترام صلاحيات كل دور:
    - admin: يرى الكل
    - finance: يرى OFFER_SELECTED + AGREEMENT_PENDING + IN_PROGRESS
    - employee: يرى الطلبات الجديدة + المسندة إليه + التي أنشأها كعميل (إن وُجد)
    - client: يرى طلباته فقط

    تدعم أيضًا منطق تقديم العرض للموظف إذا لم يقدّم سابقًا.
    """
    model = Request
    template_name = "marketplace/request_detail.html"
    context_object_name = "req"

    def get_queryset(self):
        u = self.request.user
        base = (
            Request.objects
            .select_related("client", "assigned_employee")
            .prefetch_related(
                "offers",
                Prefetch("notes", queryset=Note.objects.select_related("author"))
            )
        )
        role = getattr(u, "role", None)

        if role == "admin":
            return base
        if role == "finance":
            return base.filter(
                status__in=[
                    Request.Status.OFFER_SELECTED,
                    Request.Status.AGREEMENT_PENDING,
                    Request.Status.IN_PROGRESS,
                ]
            )
        if role == "employee":
            return base.filter(
                Q(status=Request.Status.NEW) |
                Q(assigned_employee=u) |
                Q(client=u)
            )
        return base.filter(client=u)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        req = ctx["req"]
        u = self.request.user

        ctx["can_offer"] = False
        ctx["my_offer"] = None
        ctx["offer_form"] = None
        ctx["can_create_agreement"] = False

        # منطق تقديم عرض
        if u.is_authenticated and getattr(u, "role", None) == "employee" and req.status == Request.Status.NEW and req.assigned_employee_id is None:
            my_offer = req.offers.filter(employee=u, status=Offer.Status.PENDING).first()
            ctx["my_offer"] = my_offer
            ctx["can_offer"] = my_offer is None
            if my_offer is None:
                ctx["offer_form"] = OfferCreateForm()

        # منطق إنشاء/فتح الاتفاقية (بعد اختيار العرض)
        if u.is_authenticated and getattr(u, "role", None) == "employee":
            selected = req.selected_offer
            if selected and (req.assigned_employee_id == u.id or selected.employee_id == u.id):
                if req.status == Request.Status.OFFER_SELECTED or hasattr(req, "agreement"):
                    ctx["can_create_agreement"] = True

        return ctx

    def post(self, request, *args, **kwargs):
        """
        معالجة تقديم العرض من داخل صفحة التفاصيل نفسها.
        - يجب ضبط form.instance.request/employee قبل is_valid().
        - منع التكرار: عرض PENDING واحد لكل (request, employee).
        """
        self.object = self.get_object()
        req = self.object
        u = request.user

        if not (u.is_authenticated and getattr(u, "role", None) == "employee"):
            messages.error(request, "غير مصرح بتقديم عرض على هذا الطلب.")
            return redirect("marketplace:request_detail", pk=req.pk)

        if req.status != Request.Status.NEW or req.assigned_employee_id is not None:
            messages.warning(request, "لا يمكن تقديم عروض لهذا الطلب في حالته الحالية.")
            return redirect("marketplace:request_detail", pk=req.pk)

        if req.offers.filter(employee=u, status=Offer.Status.PENDING).exists():
            messages.info(request, "قدّمت عرضًا مسبقًا لهذا الطلب.")
            return redirect("marketplace:request_detail", pk=req.pk)

        form = OfferCreateForm(request.POST or None)
        form.instance.request = req
        form.instance.employee = u

        if not form.is_valid():
            messages.error(request, "لم يتم إرسال العرض. الرجاء تصحيح الأخطاء.")
            context = self.get_context_data(object=req)
            context["offer_form"] = form
            return self.render_to_response(context)

        try:
            form.save()
        except IntegrityError:
            messages.warning(request, "لديك عرض مسبق لهذا الطلب.")
            return redirect("marketplace:request_detail", pk=req.pk)

        # إشعار العميل بعرض جديد
        try:
            off = req.offers.filter(employee=u).order_by("-id").first()
            if off:
                _notify_new_offer(off)
            else:
                _notify_link(
                    recipient=req.client,
                    title="عرض جديد على طلبك",
                    body=f"قدّم {u} عرضًا على طلبك #{req.pk}.",
                    url=reverse("marketplace:request_detail", args=[req.pk]),
                    actor=u,
                    target=req,
                )
        except Exception:
            pass

        messages.success(request, "تم تقديم العرض بنجاح.")
        return redirect("marketplace:request_detail", pk=req.pk)


# -----------------------
# العروض (المسار الأول: CBV)
# -----------------------
class OfferCreateView(LoginRequiredMixin, EmployeeOnlyMixin, CreateView):
    """
    يسمح للموظف بتقديم عرض واحد فقط لكل طلب (تحقق مسبق).
    الطلب يجب أن يكون NEW وغير مسند ليقبل عروضًا.
    """
    template_name = "marketplace/offer_create.html"
    model = Offer
    form_class = OfferCreateForm

    def dispatch(self, request, *args, **kwargs):
        self.req_obj = get_object_or_404(
            Request.objects.select_related("client"),
            pk=kwargs.get("request_id"),
            status=Request.Status.NEW,
            assigned_employee__isnull=True,
        )
        if Offer.objects.filter(request=self.req_obj, employee=request.user, status=Offer.Status.PENDING).exists():
            messages.warning(request, "قدّمت عرضًا مسبقًا لهذا الطلب. لا يمكنك تقديم أكثر من عرض واحد.")
            return redirect("marketplace:request_detail", pk=self.req_obj.pk)
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.instance.request = self.req_obj
        form.instance.employee = self.request.user
        return form

    def form_valid(self, form):
        try:
            response = super().form_valid(form)
            messages.success(self.request, "تم تقديم العرض.")
            # إشعار العميل
            try:
                _notify_new_offer(self.object)
            except Exception:
                pass
            return response
        except IntegrityError:
            messages.warning(self.request, "لديك عرض مسبق لهذا الطلب.")
            return redirect("marketplace:request_detail", pk=self.req_obj.pk)

    def get_success_url(self):
        return reverse("marketplace:request_detail", args=[self.req_obj.pk])


@login_required
@require_POST
def select_offer(request, offer_id: int):
    """
    اختيار عرض معيّن من قِبل العميل مالك الطلب (المسار الأول).
    يقبل POST فقط مع CSRF — يُحدّث SLA ويرفض باقي العروض.
    """
    offer = get_object_or_404(
        Offer.objects.select_related("request", "employee", "request__client"),
        pk=offer_id
    )
    req = offer.request

    if req.client_id != request.user.id:
        messages.error(request, "غير مصرح.")
        return redirect("marketplace:request_detail", pk=req.id)

    if offer.status == Offer.Status.SELECTED:
        messages.info(request, "هذا العرض مُختار بالفعل.")
        return redirect("marketplace:request_detail", pk=req.id)

    if req.status != Request.Status.NEW or req.assigned_employee_id is not None:
        messages.warning(request, "لا يمكن اختيار عرض في هذه المرحلة.")
        return redirect("marketplace:request_detail", pk=req.id)

    try:
        with transaction.atomic():
            offer.status = Offer.Status.SELECTED
            offer.save(update_fields=["status"])
            # سيكمل signals: إسناد + SLA + رفض بقية العروض
    except IntegrityError:
        messages.warning(request, "تم اختيار عرض آخر بالفعل لهذا الطلب.")
        return redirect("marketplace:request_detail", pk=req.id)

    # تنبيهات
    try:
        _notify_offer_selected(offer)
        _notify_link(
            recipient=req.client,
            title="تم اختيار العرض",
            body=f"تم اختيار عرض {offer.employee} لطلبك #{req.pk}.",
            url=reverse("marketplace:request_detail", args=[req.pk]),
            actor=request.user,
            target=req,
        )
    except Exception:
        pass

    messages.success(request, "تم اختيار العرض وإسناد الطلب تلقائيًا.")
    return redirect("marketplace:request_detail", pk=req.id)


class MyAssignedRequestsView(LoginRequiredMixin, EmployeeOnlyMixin, ListView):
    """الطلبات المُسنَدة للموظف الحالي."""
    template_name = "marketplace/my_assigned.html"
    context_object_name = "requests"
    paginate_by = 10

    def get_queryset(self):
        u = self.request.user
        return (
            Request.objects
            .filter(assigned_employee=u)
            .select_related("client", "assigned_employee")
            .order_by("-updated_at", "-created_at")
        )


# -----------------------
# الملاحظات على الطلب
# -----------------------
@login_required
@require_POST
def request_add_note(request, pk: int):
    """
    إضافة ملاحظة على الطلب: مسموح للعميل أو الموظف المسند أو المدير العام (admin).
    """
    req = get_object_or_404(Request, pk=pk)

    user = request.user
    role = getattr(user, 'role', None)
    allowed = (
        user.id == req.client_id
        or user.id == getattr(req, 'assigned_employee_id', None)
        or role == 'admin'
    )
    if not allowed:
        messages.error(request, "غير مصرح بإضافة ملاحظة على هذا الطلب.")
        return redirect('marketplace:request_detail', pk=req.id)

    text = (request.POST.get('text') or '').strip()
    if len(text) < 2:
        messages.error(request, "الرجاء إدخال ملاحظة صالحة (على الأقل حرفان).")
        return redirect('marketplace:request_detail', pk=req.id)

    Note.objects.create(request=req, author=user, text=text)
    messages.success(request, "تم حفظ الملاحظة.")

    # تنبيه للطرف الآخر
    try:
        url = reverse("marketplace:request_detail", args=[req.pk])
        if user.id == req.client_id:
            # العميل كتب ملاحظة → الموظف (إن وُجد)
            target_user = getattr(req, "assigned_employee", None) or (getattr(req, "selected_offer", None) and req.selected_offer.employee)
            if target_user:
                _notify_link(
                    recipient=target_user,
                    title="ملاحظة جديدة على الطلب",
                    body=f"أضاف العميل ملاحظة على الطلب #{req.pk}.",
                    url=url,
                    actor=user,
                    target=req,
                )
        else:
            # الموظف/المدير كتب ملاحظة → العميل
            _notify_link(
                recipient=req.client,
                title="ملاحظة جديدة على طلبك",
                body=f"أضيفت ملاحظة على طلبك #{req.pk}.",
                url=url,
                actor=user,
                target=req,
            )
    except Exception:
        pass

    return redirect('marketplace:request_detail', pk=req.id)


# -----------------------
# (المسار الثاني — كما كان عندك، أبقيناه بدون حذف)
# -----------------------
@login_required
def offer_create(request, request_id):
    req = get_object_or_404(Request.objects.select_related("client"), pk=request_id)
    if getattr(request.user, "role", "") not in ("employee", "admin", "manager") and not request.user.is_staff:
        return HttpResponseForbidden("غير مسموح")

    if req.status not in (Request.Status.NEW,):
        messages.error(request, "لا يمكن تقديم عرض في الحالة الحالية للطلب.")
        return redirect(req.get_absolute_url())

    if request.method == "POST":
        form = OfferForm(request.POST)
        if form.is_valid():
            exists = Offer.objects.filter(
                request=req, employee=request.user, status__in=(Offer.Status.PENDING, Offer.Status.SELECTED)
            ).exists()
            if exists:
                messages.warning(request, "لديك عرض سابق قائم على هذا الطلب.")
                return redirect(req.get_absolute_url())

            off: Offer = form.save(commit=False)
            off.request = req
            off.employee = request.user
            off.status = Offer.Status.PENDING
            off.save()

            _notify_new_offer(off)
            messages.success(request, "تم إرسال العرض للعميل.")
            return redirect(req.get_absolute_url())
        else:
            messages.error(request, "تحقّق من الحقول.")
    else:
        form = OfferForm()

    return render(request, "marketplace/offer_form.html", {"form": form, "req": req})


@login_required
def offer_detail(request, offer_id):
    off = get_object_or_404(
        Offer.objects.select_related("request", "employee", "request__client"),
        pk=offer_id,
    )
    if not off.can_view(request.user):
        return HttpResponseForbidden("غير مسموح")
    return render(request, "marketplace/offer_detail.html", {"off": off, "req": off.request})


@login_required
@transaction.atomic
def offer_select(request, offer_id):
    if request.method != "POST":
        return HttpResponseForbidden("غير مسموح")
    off = get_object_or_404(Offer.objects.select_related("request", "employee", "request__client"), pk=offer_id)
    req = off.request
    if not off.can_select(request.user):
        return HttpResponseForbidden("غير مسموح")

    off.status = Offer.Status.SELECTED
    off.save(update_fields=["status"])
    # سيقوم signals بالباقي (رفض بقية العروض + SLA + إسناد)

    try:
        _notify_offer_selected(off)
        _notify_link(
            recipient=req.client,
            title="تم اختيار العرض",
            body=f"تم اختيار عرض {off.employee} لطلبك #{req.pk}.",
            url=reverse("marketplace:request_detail", args=[req.pk]),
            actor=request.user,
            target=req,
        )
    except Exception:
        pass

    messages.success(request, "تم اختيار العرض بنجاح.")
    return redirect(req.get_absolute_url())


@login_required
@transaction.atomic
def offer_reject(request, offer_id):
    if request.method != "POST":
        return HttpResponseForbidden("غير مسموح")
    off = get_object_or_404(Offer.objects.select_related("request"), pk=offer_id)
    if not off.can_reject(request.user):
        return HttpResponseForbidden("غير مسموح")

    off.status = Offer.Status.REJECTED
    off.save(update_fields=["status"])
    # إشعار الموظف برفض عرضه (لطيف)
    try:
        _notify_link(
            recipient=off.employee,
            title="تم رفض عرضك",
            body=f"تم رفض عرضك على الطلب #{off.request_id}.",
            url=reverse("marketplace:offer_detail", args=[off.pk]) if hasattr(off, "get_absolute_url") else "",
            actor=request.user,
            target=off.request,
        )
    except Exception:
        pass

    messages.info(request, "تم رفض العرض.")
    return redirect(off.request.get_absolute_url())


# (ديتيل بديل بقي كما هو)
class RequestDetailViewAlt(DetailView):
    model = Request
    template_name = "marketplace/request_detail.html"
    context_object_name = "req"

    def get_queryset(self):
        return (Request.objects
                .select_related("client", "assigned_employee")
                .prefetch_related(
                    Prefetch("offers", queryset=Offer.objects.select_related("employee")),
                    "notes",
                ))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        req = ctx["req"]
        user = self.request.user
        ctx["can_offer"] = (
            user.is_authenticated
            and (getattr(user, "role", "") in ("employee", "admin", "manager") or user.is_staff)
            and req.status in (Request.Status.NEW,)
            and req.assigned_employee_id is None
        )
        ctx["my_offer"] = None
        if user.is_authenticated:
            ctx["my_offer"] = req.offers.filter(employee_id=user.id, status=Offer.Status.PENDING).first()
        return ctx


# -----------------------
# إجراءات المدير العام
# -----------------------
def _is_admin(u):
    return u.is_authenticated and (getattr(u, "role", None) == "admin" or getattr(u, "is_staff", False))


# إرجاع الطلب كجديد
@login_required
@user_passes_test(_is_admin)
@require_POST
def admin_request_reset_to_new(request, pk: int):
    req = get_object_or_404(Request, pk=pk)
    old_assignee = getattr(req, "assigned_employee", None)  # خزّنه قبل reset
    try:
        req.reset_to_new()
        messages.success(request, "تمت إعادة الطلب كجديد بنجاح، وأصبحت العروض السابقة مرفوضة للأرشفة.")
        # تنبيهات
        try:
            url = reverse("marketplace:request_detail", args=[pk])
            _notify_link(
                recipient=req.client,
                title="أُعيد طلبك كجديد",
                body=f"تمت إعادة الطلب #{pk} كجديد وتمت أرشفة العروض السابقة.",
                url=url,
                actor=request.user,
                target=req,
            )
            if old_assignee:
                _notify_link(
                    recipient=old_assignee,
                    title="إلغاء إسناد طلب",
                    body=f"تم إلغاء إسناد الطلب #{pk} بعد إعادته كجديد.",
                    url=url,
                    actor=request.user,
                    target=req,
                )
        except Exception:
            pass
    except Exception as e:
        messages.error(request, f"تعذّر إعادة الطلب: {e}")
    return redirect(req.get_absolute_url())


# حذف نهائي
@login_required
@user_passes_test(_is_admin)
@require_POST
def admin_request_delete(request, pk: int):
    req = get_object_or_404(Request, pk=pk)
    # خزِّن مرجعًا قبل الحذف
    title = f"[{req.pk}] {req.title}"
    client = req.client
    old_assignee = getattr(req, "assigned_employee", None)
    try:
        req.delete()
        messages.success(request, f"تم شطب الطلب نهائيًا: {title}")
        # تنبيهات (بدون رابط لأن الطلب حُذف)
        try:
            _notify(client, "تم شطب طلبك", f"تم شطب الطلب {title} نهائيًا.")
            if old_assignee:
                _notify(old_assignee, "تم شطب طلب مُسند", f"تم شطب الطلب {title} الذي كان مُسندًا إليك.")
        except Exception:
            pass
        return redirect("marketplace:request_list")
    except Exception as e:
        messages.error(request, f"تعذّر الحذف: {e}")
        return redirect(req.get_absolute_url())


# إعادة إسناد لموظف آخر
@login_required
@user_passes_test(_is_admin)
def admin_request_reassign(request, pk: int):
    req = get_object_or_404(Request, pk=pk)
    if request.method == "POST":
        form = AdminReassignForm(request.POST)
        if form.is_valid():
            employee = form.cleaned_data["employee"]
            old_assignee = getattr(req, "assigned_employee", None)
            try:
                req.reassign_to(employee)
                messages.success(request, f"تمت إعادة إسناد الطلب إلى: {employee}")
                # تنبيهات
                try:
                    url = reverse("marketplace:request_detail", args=[pk])
                    _notify_link(
                        recipient=employee,
                        title="أُسند إليك طلب",
                        body=f"تم إسناد الطلب #{pk}: {req.title}",
                        url=url,
                        actor=request.user,
                        target=req,
                    )
                    _notify_link(
                        recipient=req.client,
                        title="تحديث على طلبك",
                        body=f"تم إسناد طلبك #{pk} إلى {employee}.",
                        url=url,
                        actor=request.user,
                        target=req,
                    )
                    if old_assignee and old_assignee.id != employee.id:
                        _notify_link(
                            recipient=old_assignee,
                            title="إلغاء إسناد طلب",
                            body=f"تم سحب الطلب #{pk} من إسنادك وإسناده إلى {employee}.",
                            url=url,
                            actor=request.user,
                            target=req,
                        )
                except Exception:
                    pass
                return redirect(req.get_absolute_url())
            except Exception as e:
                messages.error(request, f"فشل إعادة الإسناد: {e}")
    else:
        form = AdminReassignForm()
    return render(request, "marketplace/admin_reassign.html", {"req": req, "form": form})
