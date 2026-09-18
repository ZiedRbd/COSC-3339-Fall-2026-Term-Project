from django import forms

from .models import Service, User


class RegisterForm(forms.Form):
    """Fields and rules for creating an account."""
    first_name = forms.CharField(
        min_length=2,
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'First name'})
    )
    last_name = forms.CharField(
        min_length=2,
        max_length=50,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Last name'})
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'Email'})
    )
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'id': 'id_password1', 'placeholder': 'Password'})
    )
    password2 = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'id': 'id_password2', 'placeholder': 'Confirm Password'})
    )

    # Django calls clean_<field> automatically while validating that field.
    # All failing rules are reported together rather than one at a time.
    def clean_password(self):
        pw_errors = []
        pw = self.cleaned_data.get("password", "")

        if not any(c.isupper() for c in pw):
            pw_errors.append(forms.ValidationError("Password needs an uppercase letter"))
        if not any(c.islower() for c in pw):
            pw_errors.append(forms.ValidationError("Password needs a lowercase letter"))
        if not any(c.isdigit() for c in pw):
            pw_errors.append(forms.ValidationError("Password needs a number"))
        if not any(not c.isalnum() for c in pw):
            pw_errors.append(forms.ValidationError("Password needs a symbol"))

        if pw_errors:
            raise forms.ValidationError(pw_errors)

        return pw

    # Runs after every field has been cleaned. Compares the two passwords
    # only if both survived their own validation.
    def clean(self):
        data = super().clean()
        pw, pw2 = data.get("password"), data.get("password2")
        if pw and pw2 and pw != pw2:
            self.add_error("password2", "Passwords do not match")
        return data

    # Emails are stored lowercase so the same address cannot register twice
    # with different capitalization.
    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered")
        return email


class LoginForm(forms.Form):
    """Email and password for signing in. Credentials are checked in the view."""
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-input', 'placeholder': 'Email'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-input', 'id': 'id_password', 'placeholder': 'Password'})
    )


class IncidentForm(forms.Form):
    """Fields for creating or editing a ticket. Used by both views."""
    title = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Brief title'})
    )
    description = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input text-field', 'rows': 4})
    )

    # Optional location details
    building = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Building (optional)'})
    )
    room = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Room (optional)'})
    )

    # Dropdown of every service in the database
    service = forms.ModelChoiceField(
        queryset=Service.objects.all(),
        empty_label="Select a service"
    )

    # How urgent the reporter thinks it is
    priority = forms.ChoiceField(
        choices=[
            ("low", "Low"),
            ("medium", "Medium"),
            ("high", "High"),
            ("critical", "Critical"),
        ],
        initial="medium",
    )
