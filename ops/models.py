from django.db import models
from django.contrib.auth.models import AbstractUser


# Anyone who can sign in. AbstractUser supplies username, password,
# first_name, last_name, and is_active. The email is also stored as the
# username so it acts as the login field.
class User(AbstractUser):
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, default="user")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email


# A group that handles tickets, such as Plumbing or IT Support
class Team(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
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
# Each service is owned by one team. Criticality is reserved for
# escalation rules in later sprints.
class Service(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    owning_team = models.ForeignKey(Team, on_delete=models.PROTECT)
    criticality = models.CharField(max_length=20, default="medium")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


# A ticket filed by a user about a service. The assignment, escalation,
# and SLA fields exist for later sprints and stay empty in Sprint 1.
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
    status = models.CharField(max_length=20, default="open")
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


# A note or progress report written on a ticket. Not used in Sprint 1.
class IncidentUpdate(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE)
    author = models.ForeignKey(User, on_delete=models.PROTECT)
    update_type = models.CharField(max_length=20, default="note")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Update on {self.incident}"
