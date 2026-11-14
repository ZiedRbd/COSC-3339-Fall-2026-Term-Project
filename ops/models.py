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
    # Profile picture. The database holds only the file's path under
    # MEDIA_ROOT; the image itself is a file in media/avatars/.
    avatar = models.ImageField(upload_to="avatars/", blank=True)


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
# Criticality describes the service; escalation uses the ticket's severity.
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
# to that solver. The escalation fields record where the ticket stands
# in its team's policy.
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
    # When the wait at the current tier began: the moment the ticket was
    # given to its solver, by assignment, hand-out from the queue,
    # reassignment, reopening or escalation. The minute timer compares
    # now minus this against the tier's wait.
    escalation_timer_started_at = models.DateTimeField(null=True, blank=True)
    # True once every tier of the team's policy has run out. The ticket
    # is then shown unassigned at the top of the list until someone takes it.
    is_unassigned_after_escalation = models.BooleanField(default=False)
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


# One on-call shift. One solver covers a team between starts_at and
# ends_at. The interval is half open: the end instant belongs to the next
# shift. Only the team lead creates these. The primary takes tickets
# first; the secondary takes them once the primary holds three.
class Shift(models.Model):
    ON_CALL_ROLE_CHOICES = [
        ("primary", "Primary"),
        ("secondary", "Secondary"),
    ]
    team = models.ForeignKey(Team, on_delete=models.PROTECT, related_name="shifts")
    solver = models.ForeignKey(User, on_delete=models.PROTECT, related_name="shifts")
    on_call_role = models.CharField(max_length=10, choices=ON_CALL_ROLE_CHOICES, default="primary")
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
        return f"{self.solver} {self.on_call_role} on call for {self.team}"


# One step of a team's escalation policy. Tier 1 is always the on-call
# solver who first got the ticket. Each later tier names a role (the team
# lead) or a user (one person on the team). When the person at a tier has
# not started work within wait_minutes, the ticket moves to the next
# tier. After the last tier it is marked unassigned.
class EscalationTier(models.Model):
    ESCALATE_TO_CHOICES = [
        ("on_call", "The on-call solver"),
        ("lead", "The team lead"),
        ("user", "A specific person on the team"),
    ]
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="escalation_tiers")
    tier_number = models.PositiveIntegerField()
    escalate_to = models.CharField(max_length=20, choices=ESCALATE_TO_CHOICES)
    # Only set when escalate_to is "user"
    escalate_to_user = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )
    # How long the person at this tier has before the ticket moves on
    wait_minutes = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["team", "tier_number"]
        constraints = [
            models.UniqueConstraint(fields=["team", "tier_number"], name="one_tier_per_number_per_team"),
            models.CheckConstraint(
                condition=models.Q(wait_minutes__isnull=True) | models.Q(wait_minutes__gt=0),
                name="tier_wait_is_positive",
            ),
        ]

    def __str__(self):
        return f"{self.team} tier {self.tier_number}: {self.get_escalate_to_display()}"


# One message to one person about one ticket. The bell counts rows with
# no read_at. emailed_at is when the same message went out by email, and
# stays empty when the mail server refused it.
class Notification(models.Model):
    EVENT_CHOICES = [
        ("assigned", "Assigned to you"),
        ("escalated", "Escalated to you"),
        ("final_escalation", "Escalation ran out"),
        ("queued", "Ticket is waiting in the queue"),
        ("work_started", "Work started on your ticket"),
        ("resolved", "Your ticket was resolved"),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE, null=True, blank=True)
    event = models.CharField(max_length=20, choices=EVENT_CHOICES)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"])]

    def __str__(self):
        return f"{self.get_event_display()} for {self.user}"
