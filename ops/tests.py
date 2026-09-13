from django.test import TestCase
from .models import User


# Run with: python manage.py test ops
# Each test gets a fresh empty database. self.client acts as a browser.
class EmailCaseTests(TestCase):
    """Emails must work the same no matter how they are capitalized."""

    # Helper that submits the registration form with a given email
    # so each test does not repeat the same five fields
    def register(self, email):
        return self.client.post("/register/", {
            "first_name": "Test",
            "last_name": "User",
            "email": email,
            "password": "Good!Pass1",
            "password2": "Good!Pass1",
        })

    def test_email_is_stored_lowercase(self):
        self.register("Test@Example.com")
        self.assertTrue(User.objects.filter(email="test@example.com").exists())

    def test_duplicate_email_rejected_regardless_of_case(self):
        self.register("test@example.com")
        self.register("TEST@EXAMPLE.COM")
        self.assertEqual(User.objects.filter(email="test@example.com").count(), 1)

    def test_login_works_with_different_case(self):
        self.register("test@example.com")
        response = self.client.post("/login/", {
            "email": "TEST@Example.COM",
            "password": "Good!Pass1",
        })
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("login", response.url)
