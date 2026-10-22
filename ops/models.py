from django.db import models
from django.contrib.auth.models import AbstractUser


# Anyone who can sign in. AbstractUser supplies username, password,
# first_name, last_name, and is_active. The email is also stored as the
# username so it acts as the login field.
class User(AbstractUser):
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, default="reporter")
    created_at = models.DateTimeField(auto_now_add=True)
    bio = models.TextField(blank=True)


    def __str__(self):
        return self.email


# A group that handles tickets, such as Plumbing or IT Support.
# The lead schedules the team's on-call shifts and can reassign its
# tickets. Lead is a column here, not a role value, so a user may lead
# any number of teams and finding a team's lead is one read of this row.
class Team(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    lead = models.ForeignKey(
        "User", on_delete=models.PROTECT, null=True, blank=True, related_name="led_teams"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


# Join table between users and teams. A user can be on many teams and a
# team can have many users.
class TeamMember(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # The same user cannot be added to the same team twice
        unique_together = ["user", "team"]

    def __str__(self):
        return f"{self.user} in {self.team}"


# Something the campus supports, such as Wi-Fi or restroom plumbing.
# A service is usually owned by one team. It can have no team, in which
# case tickets filed against it cannot be assigned to a solver.
# Criticality is reserved for escalation rules in later sprints.
class Service(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    owning_team = models.ForeignKey(Team, on_delete=models.PROTECT, null=True, blank=True)
    criticality = models.CharField(max_length=20, default="medium")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


# A ticket filed by a user about a service. On creation it is routed to
# the team that owns the service and, when someone is on call, assigned
# to that solver. Escalation and SLA fields are for later sprints.
class Incident(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    # Where on campus the problem is. Both optional.
    building = models.CharField(max_length=100, blank=True)
    room = models.CharField(max_length=50, blank=True)
    service = models.ForeignKey(Service, on_delete=models.PROTECT)
    reported_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="reported_incidents")
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_incidents")
    assigned_team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True)
    STATUS_CHOICES = [
        ("open", "Open"),
        ("assigned", "Assigned"),
        ("in_progress", "In Progress"),
        ("resolved", "Resolved"),
        ("closed", "Closed"),
    ]
    status = models.CharField(max_length=20,choices=STATUS_CHOICES, default="open")
    priority = models.CharField(max_length=20, default="medium")
    escalation_level = models.IntegerField(default=0)
    escalated_at = models.DateTimeField(null=True, blank=True)
    sla_due_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    # Soft delete flag. Deleted tickets are hidden, never removed.
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


# One entry on a ticket's timeline: creation, a status change, an edit,
# a comment, a note, or an assignment. Written by the system, never
# edited. old/new pairs record both sides of a change.
class IncidentUpdate(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE)
    author = models.ForeignKey(User, on_delete=models.PROTECT)
    update_type = models.CharField(max_length=20, default="note")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    old_status = models.CharField(max_length=20, blank=True)
    new_status = models.CharField(max_length=20, blank=True)
    # Set on assignment and reassignment entries only
    old_assignee = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    new_assignee = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    def __str__(self):
        return f"Update on {self.incident}"


# One on-call shift. Exactly one solver covers a team between
# starts_at and ends_at. The interval is half open: the end instant
# belongs to the next shift. Only the team lead creates these.
class Shift(models.Model):
    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="shifts")
    solver = models.ForeignKey(User, on_delete=models.PROTECT, related_name="shifts")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="scheduled_shifts")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["team", "starts_at"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ends_at__gt=models.F("starts_at")),
                name="shift_ends_after_it_starts",
            )
        ]

    def __str__(self):
        return f"{self.solver} on call for {self.team}"
