# core/management/commands/check_sla.py
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta

from marketplace.models import Request
from notifications.utils import notify_user, notify_admins

class Command(BaseCommand):
    help = "فحص مهلة إنشاء الاتفاقية: تنبيه إذا تجاوزت 3 أيام من offer_selected."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="تعطيل الإرسال والاكتفاء بالعرض.")

    def handle(self, *args, **opts):
        now = timezone.now()
        qs = Request.objects.filter(
            status=Request.Status.OFFER_SELECTED,
            agreement_due_at__isnull=False,
            sla_agreement_overdue=False,  # لم ننبه سابقًا
            agreement_due_at__lt=now      # فات الموعد
        )
        count = 0
        for req in qs.select_related("client", "assigned_employee"):
            count += 1
            req.sla_agreement_overdue = True
            req.save(update_fields=["sla_agreement_overdue", "updated_at"])

            title = f"تأخير إنشاء الاتفاقية لطلب #{req.id}"
            msg = (
                f"تأخر إنشاء الاتفاقية لطلب #{req.id} — {req.title}\n"
                f"العميل: {req.client.name or req.client.email}\n"
                f"الموظف: {getattr(req.assigned_employee, 'name', None) or getattr(req.assigned_employee, 'email', '')}\n"
                f"تاريخ اختيار العرض: {req.offer_selected_at.strftime('%Y-%m-%d %H:%M') if req.offer_selected_at else '—'}\n"
                f"موعد الاستحقاق: {req.agreement_due_at.strftime('%Y-%m-%d %H:%M') if req.agreement_due_at else '—'}\n"
                f"الرجاء إنشاء الاتفاقية أو التواصل لمعالجة التأخير."
            )

            if not opts["dry_run"]:
                # تنبيه الموظف المسند + المدير العام
                if req.assigned_employee:
                    notify_user(req.assigned_employee, title, msg, level="alert", email_subject=title)
                notify_admins(title, msg, level="alert")

        self.stdout.write(self.style.SUCCESS(f"SLA: فُحصت الطلبات المتأخرة، تم التبليغ عن {count} طلب/طلبات."))
