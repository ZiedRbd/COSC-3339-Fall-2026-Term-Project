from django.core.management.base import BaseCommand
from ops.models import User, Team, TeamMember, Service, Incident


# Loads demo data. Safe to run more than once, existing rows are reused.
# Run with: python manage.py seed
class Command(BaseCommand):
    help = "Load demo teams, services, users, and incidents"

    def handle(self, *args, **options):
        teams = {}
        for name, desc in [
            ("Plumbing", "Water, drains, restrooms, and leaks"),
            ("Electrical", "Lighting, outlets, and power"),
            ("IT Support", "Wi-Fi, printing, and classroom technology"),
        ]:
            teams[name], _ = Team.objects.get_or_create(name=name, defaults={"description": desc})

        services = {}
        for name, desc, team, crit in [
            ("Restroom Plumbing", "Leaks, clogs, and broken fixtures", "Plumbing", "high"),
            ("Water Fountains", "Fountains and bottle fillers", "Plumbing", "low"),
            ("Classroom Lighting", "Burned out or flickering lights", "Electrical", "medium"),
            ("Power Outlets", "Dead or damaged outlets", "Electrical", "medium"),
            ("Campus Wi-Fi", "Wireless connectivity in all buildings", "IT Support", "critical"),
            ("Printing", "Lab and library printers", "IT Support", "medium"),
        ]:
            services[name], _ = Service.objects.get_or_create(
                name=name, defaults={"description": desc, "owning_team": teams[team], "criticality": crit}
            )

        users = {}
        for email, first, last, team in [
            ("demo@campusdesk.edu", "Demo", "User", None),
            ("maria.lopez@campusdesk.edu", "Maria", "Lopez", "Plumbing"),
            ("james.chen@campusdesk.edu", "James", "Chen", "Electrical"),
            ("aisha.khan@campusdesk.edu", "Aisha", "Khan", "IT Support"),
            ("tom.rivera@campusdesk.edu", "Tom", "Rivera", "IT Support"),
        ]:
            user = User.objects.filter(email=email).first()
            if not user:
                user = User.objects.create_user(
                    username=email, email=email, password="Demo!Pass1", first_name=first, last_name=last
                )
            users[email] = user
            if team:
                TeamMember.objects.get_or_create(user=user, team=teams[team])

        reporter = users["demo@campusdesk.edu"]
        for title, desc, service, priority, building, room in [
            ("Sink leaking in Moody 2nd floor restroom", "Steady drip under the sink", "Restroom Plumbing", "high", "Moody", "214"),
            ("Water fountain not working", "No water pressure at all", "Water Fountains", "low", "Trustee", "1st floor"),
            ("Lights flickering in room 114", "Two panels flicker all day", "Classroom Lighting", "medium", "Fleck", "114"),
            ("Hallway lights out", "Entire east hallway is dark", "Classroom Lighting", "high", "Doyle", "East wing"),
            ("Outlet sparked in dorm lounge", "Sparked when plugging in a laptop", "Power Outlets", "high", "Teresa Hall", "Lounge"),
            ("Dead outlets along back wall", "None of the six outlets work", "Power Outlets", "medium", "Fleck", "203"),
            ("No Wi-Fi in the library basement", "Cannot connect on any device", "Campus Wi-Fi", "critical", "Library", "Basement"),
            ("Wi-Fi drops every few minutes", "Keeps disconnecting during class", "Campus Wi-Fi", "high", "Moody", "301"),
            ("Printer jammed in lab 3", "Paper jam light on, cannot clear", "Printing", "low", "Library", "Lab 3"),
            ("Printer out of toner", "Prints are faded and streaky", "Printing", "low", "Trustee", "Copy room"),
        ]:
            Incident.objects.get_or_create(
                title=title,
                defaults={
                    "description": desc,
                    "service": services[service],
                    "reported_by": reporter,
                    "priority": priority,
                    "building": building,
                    "room": room,
                },
            )

        self.stdout.write(self.style.SUCCESS(
            f"Seeded: {Team.objects.count()} teams, {Service.objects.count()} services, "
            f"{User.objects.count()} users, {Incident.objects.count()} incidents"
        ))
