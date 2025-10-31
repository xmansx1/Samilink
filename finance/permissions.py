# finance/permissions.py
def is_finance(user) -> bool:
    role = getattr(user, "role", "")
    return bool(getattr(user, "is_superuser", False) or getattr(user, "is_staff", False) or role == "finance")
