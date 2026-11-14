from django.core.management.base import BaseCommand

from ops.scheduling import assign_all_waiting, escalate_due


# Moves every overdue ticket to the next tier of its team's policy, then
# hands waiting tickets to whoever on call has room. On the server a
# systemd timer runs this once a minute: see deploy/escalate.timer.
# Run by hand with: python manage.py escalate
class Command(BaseCommand):
    help = "Escalate overdue Assigned tickets and hand out tickets that are waiting"

    def handle(self, *args, **options):
        moved = escalate_due()
        assigned = assign_all_waiting()
        self.stdout.write(f"{moved} ticket(s) escalated, {assigned} waiting ticket(s) assigned")
