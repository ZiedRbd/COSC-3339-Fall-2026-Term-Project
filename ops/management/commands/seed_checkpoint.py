"""
The demo accounts the Sprint 5 checkpoint asks for: an administrator and
an auditor. Safe to run on a database that is in use. An account that
already exists is left exactly as it is, password included, and nothing
else is touched.

    python manage.py seed_checkpoint
"""
from django.core.management.base import BaseCommand

from ops.management.commands.seed import PASSWORD
from ops.models import User

ACCOUNTS = [
    # email, first name, last name, role, administrator
    ("demo.admin@campusdesk.edu", "Demo", "Admin", "reporter", True),
    ("demo.auditor@campusdesk.edu", "Demo", "Auditor", "auditor", False),
]


class Command(BaseCommand):
    help = "Adds the demo administrator and the demo auditor when they are missing."

    def handle(self, *args, **options):
        for email, first_name, last_name, role, administrator in ACCOUNTS:
            if User.objects.filter(email=email).exists():
                self.stdout.write(f"{email} is already there, left as it is")
                continue
            user = User.objects.create_user(username=email, email=email, password=PASSWORD,
                                            first_name=first_name, last_name=last_name, role=role)
            if administrator:
                user.is_superuser = True
                user.save()
            self.stdout.write(self.style.SUCCESS(f"{email} was added"))
