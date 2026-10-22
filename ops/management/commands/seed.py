from django.core.management.base import BaseCommand

from ops.models import User, Team, TeamMember, Service, Incident
from ops.scheduling import assign_on_creation
from ops.timeline import log_event

PASSWORD = "Demo!Pass1"


# Loads demo data. Safe to run more than once, existing rows are reused.
# Every account's email ends with its role, so it is obvious who is who:
# name.reporter@, name.solver@, name.leadsolver@. All share one password.
# Creates six reporters and ten solvers, three per team, two of them leads,
# and two dozen tickets in every state. Run with: python manage.py seed
# Follow with: python manage.py seed_shifts, which lays a week of cover and
# hands out every ticket that is still waiting.
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
                    username=email, email=email, password=PASSWORD,
                    first_name=first, last_name=last,
                )
            user.role = role
            user.save()
            if team:
                TeamMember.objects.get_or_create(user=user, team=teams[team])
            return user

        # Six reporters, including the demo account used for the submission login
        reporters = [
            make_user("demo.reporter@campusdesk.edu", "Demo", "User", "reporter"),
            make_user("maria.lopez.reporter@campusdesk.edu", "Maria", "Lopez", "reporter"),
            make_user("james.chen.reporter@campusdesk.edu", "James", "Chen", "reporter"),
            make_user("aisha.khan.reporter@campusdesk.edu", "Aisha", "Khan", "reporter"),
            make_user("tom.rivera.reporter@campusdesk.edu", "Tom", "Rivera", "reporter"),
            make_user("drmichaelsreporter@campusdesk.edu", "Doctor", "Michaels", "reporter"),
        ]

        # Three solvers on each team. Pat leads Plumbing and Electrical and
        # takes Plumbing shifts. Maya leads IT Support from outside any team,
        # so she takes no shifts. One lead on the rota and one off it is what
        # the sprint roster asks for.
        members = {
            "Plumbing": [
                make_user("pat.diaz.leadsolver@campusdesk.edu", "Pat", "Diaz", "solver", "Plumbing"),
                make_user("emma.walsh.solver@campusdesk.edu", "Emma", "Walsh", "solver", "Plumbing"),
                make_user("ben.carter.solver@campusdesk.edu", "Ben", "Carter", "solver", "Plumbing"),
            ],
            "Electrical": [
                make_user("sam.okoro.solver@campusdesk.edu", "Sam", "Okoro", "solver", "Electrical"),
                make_user("omar.haddad.solver@campusdesk.edu", "Omar", "Haddad", "solver", "Electrical"),
                make_user("jack.miller.solver@campusdesk.edu", "Jack", "Miller", "solver", "Electrical"),
            ],
            "IT Support": [
                make_user("lee.nguyen.solver@campusdesk.edu", "Lee", "Nguyen", "solver", "IT Support"),
                make_user("nina.park.solver@campusdesk.edu", "Nina", "Park", "solver", "IT Support"),
                make_user("drmichaelssolver@campusdesk.edu", "Doctor", "Michaels", "solver", "IT Support"),
            ],
        }
        maya = make_user("maya.ortiz.leadsolver@campusdesk.edu", "Maya", "Ortiz", "solver")
        for team_name, lead in [
            ("Plumbing", members["Plumbing"][0]),
            ("Electrical", members["Plumbing"][0]),
            ("IT Support", maya),
        ]:
            teams[team_name].lead = lead
            teams[team_name].save()

        # Two dozen tickets across every service, reporter and state.
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
            (4, "Toilet overflowing in Doyle 1st floor", "Restroom Plumbing", "critical", "Doyle", "108", "in_progress"),
            (4, "Bottle filler dripping nonstop", "Water Fountains", "low", "Fleck", "2nd floor", "closed"),
            (5, "Projector outlet dead in lecture hall", "Power Outlets", "high", "Moody", "Auditorium", "assigned"),
            (5, "Office Wi-Fi unreachable since Monday", "Campus Wi-Fi", "high", "Fleck", "310", "open"),
            (5, "Classroom lights stay on all night", "Classroom Lighting", "low", "Doyle", "210", "resolved"),
            (0, "Shower drain clogged in Teresa Hall", "Restroom Plumbing", "medium", "Teresa Hall", "2B", "closed"),
            (3, "Lab printer prints blank pages", "Printing", "medium", "Library", "Lab 1", "assigned"),
            (2, "Hand dryer sparks when used", "Power Outlets", "critical", "Trustee", "Restroom 2", "in_progress"),
            (4, "Fountain water tastes metallic", "Water Fountains", "medium", "Doyle", "Gym hall", "open"),
            (1, "Wi-Fi login page never loads", "Campus Wi-Fi", "medium", "Library", "3rd floor", "resolved"),
            (0, "Lost my wallet near the gym", "Lost and Found", "low", "Rec Center", "Lobby", "open"),
            (3, "Found a set of keys in Fleck", "Lost and Found", "low", "Fleck", "Front desk", "open"),
            (5, "Emergency light flickering in stairwell", "Classroom Lighting", "high", "Moody", "Stairwell B", "assigned"),
            (4, "Printer queue stuck for the whole lab", "Printing", "high", "Trustee", "Lab 2", "open"),
        ]

        labels = dict(Incident.STATUS_CHOICES)

        def path_to(target):
            """The ordered list of statuses to reach target from open."""
            order = ["open", "assigned", "in_progress", "resolved", "closed"]
            return order[1:order.index(target) + 1]

        for n, (idx, title, service_name, severity, building, room, final) in enumerate(tickets):
            service = services[service_name]
            team = service.owning_team
            incident, created = Incident.objects.get_or_create(
                title=title,
                defaults={
                    "description": f"Reported issue: {title.lower()}.",
                    "service": service,
                    "reported_by": reporters[idx],
                    "assigned_team": team,
                    "priority": severity,
                    "building": building,
                    "room": room,
                },
            )
            if not created:
                continue
            routed = f" and routed to {team.name}" if team else ""
            log_event(incident, reporters[idx], "created", f"Ticket created{routed}")
            if final == "open":
                # Exactly what happens to a real ticket: nobody on call yet, so it
                # waits. seed_shifts hands it out once the week is covered.
                assign_on_creation(incident)
                continue
            # Walk the ticket to its final status as one of the team's solvers
            solver = members[team.name][n % 3]
            incident.assigned_to = solver
            incident.save()
            log_event(incident, reporters[idx], "assignment",
                      f"Assigned to {solver.first_name} {solver.last_name}, on call for {team.name}",
                      new_assignee=solver)
            for status in path_to(final):
                prev = incident.status
                incident.status = status
                incident.save()
                log_event(incident, solver, "status_change",
                          f"Status changed from {labels[prev]} to {labels[status]}",
                          old_status=prev, new_status=status)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded: {Team.objects.count()} teams, {Service.objects.count()} services, "
            f"{User.objects.filter(role='reporter').count()} reporters, "
            f"{User.objects.filter(role='solver').count()} solvers, "
            f"{Incident.objects.count()} incidents"
        ))
