from django.core.management.base import BaseCommand

from ops.models import User, Team, TeamMember, Service, Incident, IncidentUpdate
from ops.timeline import log_event


# Loads demo data. Safe to run more than once, existing rows are reused.
# Creates six reporters and ten solvers, three per team. Two of the solvers lead teams.
# Run with: python manage.py seed
class Command(BaseCommand):
    help = "Load demo teams, services, users (6 reporters + 10 solvers), and incidents"

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
            # No owning team on purpose: a ticket against it cannot be assigned
            ("Lost and Found", "Items turned in around campus", None, "low"),
        ]:
            services[name], _ = Service.objects.get_or_create(
                name=name, defaults={
                    "description": desc, "owning_team": teams[team] if team else None, "criticality": crit,
                }
            )

        def make_user(email, first, last, role, team=None):
            user = User.objects.filter(email=email).first()
            if not user:
                user = User.objects.create_user(
                    username=email, email=email, password="Demo!Pass1",
                    first_name=first, last_name=last,
                )
            user.role = role
            user.save()
            if team:
                TeamMember.objects.get_or_create(user=user, team=teams[team])
            return user

        # Six reporters, including the demo account used for the submission login
        reporters = [
            make_user("demo@campusdesk.edu", "Demo", "User", "reporter"),
            make_user("maria.lopez@campusdesk.edu", "Maria", "Lopez", "reporter"),
            make_user("james.chen@campusdesk.edu", "James", "Chen", "reporter"),
            make_user("aisha.khan@campusdesk.edu", "Aisha", "Khan", "reporter"),
            make_user("tom.rivera@campusdesk.edu", "Tom", "Rivera", "reporter"),
            make_user("drmichaelsreporter@campusdesk.edu", "Doctor", "Michaels", "reporter"),
        ]

        # Three solvers on each team, plus one more below who leads IT Support
        solvers = {
            "Plumbing": make_user("pat.diaz@campusdesk.edu", "Pat", "Diaz", "solver", "Plumbing"),
            "Plumbing 2": make_user("emma.walsh@campusdesk.edu", "Emma", "Walsh", "solver", "Plumbing"),
            "Plumbing 3": make_user("ben.carter@campusdesk.edu", "Ben", "Carter", "solver", "Plumbing"),
            "Electrical": make_user("sam.okoro@campusdesk.edu", "Sam", "Okoro", "solver", "Electrical"),
            "Electrical 2": make_user("omar.haddad@campusdesk.edu", "Omar", "Haddad", "solver", "Electrical"),
            "Electrical 3": make_user("jack.miller@campusdesk.edu", "Jack", "Miller", "solver", "Electrical"),
            "IT Support": make_user("lee.nguyen@campusdesk.edu", "Lee", "Nguyen", "solver", "IT Support"),
            "IT Support 2": make_user("nina.park@campusdesk.edu", "Nina", "Park", "solver", "IT Support"),
            "Prof": make_user("drmichaelssolver@campusdesk.edu", "Doctor", "Michaels", "solver", "IT Support"),
        }

        # Team leads. Pat leads Plumbing and Electrical and takes shifts on
        # Plumbing. Maya leads IT Support and is on no team, so she takes no
        # shifts. One lead on the rota and one off it is what the roster needs.
        solvers["Lead IT"] = make_user("maya.ortiz@campusdesk.edu", "Maya", "Ortiz", "solver")
        for team_name, lead in [
            ("Plumbing", solvers["Plumbing"]),
            ("Electrical", solvers["Plumbing"]),
            ("IT Support", solvers["Lead IT"]),
        ]:
            teams[team_name].lead = lead
            teams[team_name].save()

        # Ten incidents across the services, each routed to the owning team.
        # (reporter_index, title, service, severity, building, room, final_status)
        tickets = [
            (0, "Sink leaking in Moody 2nd floor restroom", "Restroom Plumbing", "high", "Moody", "214", "open"),
            (1, "Water fountain not working", "Water Fountains", "low", "Trustee", "1st floor", "assigned"),
            (1, "Lights flickering in room 114", "Classroom Lighting", "medium", "Fleck", "114", "in_progress"),
            (2, "Hallway lights out", "Classroom Lighting", "high", "Doyle", "East wing", "resolved"),
            (2, "Outlet sparked in dorm lounge", "Power Outlets", "high", "Teresa Hall", "Lounge", "closed"),
            (3, "Dead outlets along back wall", "Power Outlets", "medium", "Fleck", "203", "open"),
            (3, "No Wi-Fi in the library basement", "Campus Wi-Fi", "critical", "Library", "Basement", "in_progress"),
            (0, "Wi-Fi drops every few minutes", "Campus Wi-Fi", "high", "Moody", "301", "assigned"),
            (1, "Printer jammed in lab 3", "Printing", "low", "Library", "Lab 3", "resolved"),
            (2, "Printer out of toner", "Printing", "low", "Trustee", "Copy room", "open"),
        ]

        def path_to(target):
            """The ordered list of statuses to reach target from open."""
            order = ["open", "assigned", "in_progress", "resolved", "closed"]
            return order[1:order.index(target) + 1]

        for idx, title, service_name, severity, building, room, final in tickets:
            service = services[service_name]
            incident, created = Incident.objects.get_or_create(
                title=title,
                defaults={
                    "description": f"Reported issue: {title.lower()}.",
                    "service": service,
                    "reported_by": reporters[idx],
                    "assigned_team": service.owning_team,
                    "priority": severity,
                    "building": building,
                    "room": room,
                },
            )
            if not created:
                continue
            log_event(incident, reporters[idx], "created",
                      f"Ticket created and assigned to {service.owning_team.name}")
            # Walk the ticket up to its final status, logging each move as a solver
            solver = TeamMember.objects.filter(team=service.owning_team).first().user
            for status in path_to(final):
                prev = incident.status
                incident.status = status
                incident.assigned_to = solver
                incident.save()
                log_event(incident, solver, "status_change",
                          f"Status changed from {prev} to {status}",
                          old_status=prev, new_status=status)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded: {Team.objects.count()} teams, {Service.objects.count()} services, "
            f"{User.objects.filter(role='reporter').count()} reporters, "
            f"{User.objects.filter(role='solver').count()} solvers, "
            f"{Incident.objects.count()} incidents"
        ))
