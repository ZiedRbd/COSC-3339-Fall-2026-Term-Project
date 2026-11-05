from django.core.management.base import BaseCommand

from ops.scheduling import escalate_due


# Moves every overdue ticket to the next tier of its team's policy. On the
# server a systemd timer runs this once a minute: see deploy/escalate.timer.
# Run by hand with: python manage.py escalate
class Command(BaseCommand):
    help = "Escalate every Assigned ticket whose solver has not started work in time"

    def handle(self, *args, **options):
        moved = escalate_due()
        self.stdout.write(f"{moved} ticket(s) escalated")
