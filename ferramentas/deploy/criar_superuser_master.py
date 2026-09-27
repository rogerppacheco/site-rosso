import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core_config.settings")
django.setup()
from django.contrib.auth import get_user_model
USERNAME = os.environ.get("NV_MASTER_USER", "admin")
EMAIL = os.environ.get("NV_MASTER_EMAIL", "admin@futuratelecom.com.br")
PASSWORD = os.environ["NV_MASTER_PASSWORD"]
User = get_user_model()
user, created = User.objects.get_or_create(username=USERNAME, defaults={"email": EMAIL, "is_staff": True, "is_superuser": True})
user.email = EMAIL
user.is_staff = True
user.is_superuser = True
user.is_active = True
user.set_password(PASSWORD)
user.save()
print(("CREATED" if created else "UPDATED"), USERNAME, EMAIL, "id=", user.pk)
