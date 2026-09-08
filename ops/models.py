from django.db import models
from django.contrib.auth.models import AbstractUser


# Anyone who can log in
# AbstractUser already gives us email password first_name last_name and is_active
class User(AbstractUser):
    email = models.EmailField(unique=True)
    role = models.CharField(max_length=20, default="user")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.email


# An IT group such as Networking or Hardware
class Team(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


# Links users to teams
# One user can be on many teams and one team can have many users
class TeamMember(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["user", "team"]

    def __str__(self):
        return f"{self.user} in {self.team}"


# Something IT supports such as Wifi or Printing
# Each service is owned by one team
class Service(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    owning_team = models.ForeignKey(Team, on_delete=models.PROTECT)
    criticality = models.CharField(max_length=20, default="medium")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


# A ticket filed by a user about a service
# assigned_to assigned_team escalation and sla fields stay empty until later sprints
class Incident(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
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
    is_deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


# A note or report written on a ticket
# Not used in sprint one
class IncidentUpdate(models.Model):
    incident = models.ForeignKey(Incident, on_delete=models.CASCADE)
    author = models.ForeignKey(User, on_delete=models.PROTECT)
    update_type = models.CharField(max_length=20, default="note")
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Update on {self.incident}"
