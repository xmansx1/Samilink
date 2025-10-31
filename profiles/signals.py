from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from .models import EmployeeProfile
from django.contrib.auth import get_user_model

User = get_user_model()

@receiver(post_save, sender=User)
def create_employee_profile(sender, instance, created, **kwargs):
    # إنشاء بروفايل تلقائيًا للمستخدمين من نوع employee
    if created and getattr(instance, "role", None) == "employee":
        EmployeeProfile.objects.get_or_create(user=instance)
