"""Shared test helpers."""

from ops.models import Service, Team, User


GOOD_PASSWORD = "Good!Pass1"


def register(client, email, password=GOOD_PASSWORD, password2=None):
    """Submit the registration form. password2 defaults to password."""
    return client.post("/register/", {
        "first_name": "Test",
        "last_name": "User",
        "email": email,
        "password": password,
        "password2": password2 if password2 is not None else password,
    })


def make_user(email="user@example.com"):
    """Create a user directly, bypassing the form."""
    return User.objects.create_user(
        username=email, email=email, password=GOOD_PASSWORD,
        first_name="Test", last_name="User",
    )


def make_service():
    """Create one team and one service to file tickets against."""
    team = Team.objects.create(name="Plumbing")
    return Service.objects.create(name="Restroom Plumbing", owning_team=team)
