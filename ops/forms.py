from django import forms
from django.utils import timezone

from .models import Service, Shift, User


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

    # Severity: how serious the incident is. Required, no default, so the
    # reporter makes a deliberate choice. Labels explain each level.
    priority = forms.ChoiceField(
        label="Severity",
        choices=[
            ("", "Select a severity level"),
            ("low", "Low - minor inconvenience, service still works"),
            ("medium", "Medium - partial disruption, a workaround exists"),
            ("high", "High - major disruption, no workaround"),
            ("critical", "Critical - safety hazard or full outage"),
        ],
    )


class DateAndHourWidget(forms.MultiWidget):
    """
    A date picker next to a 24-hour clock dropdown (00:00 to 23:00), so a
    shift time reads 16:00 and never 4:00 PM. Posts as name_0 and name_1.
    """
    def __init__(self, attrs=None):
        hours = [(f"{h:02d}:00", f"{h:02d}:00") for h in range(24)]
        super().__init__([forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                          forms.Select(choices=hours)], attrs)

    def decompress(self, value):
        """Split a stored instant into the local date and HH:MM the two inputs show."""
        if value:
            local = timezone.localtime(value)
            return [local.date(), local.strftime("%H:%M")]
        return [None, None]


class ShiftForm(forms.ModelForm):
    """
    One on-call shift for a team. The solver list only offers active
    solvers who are on that team. A shift must end after it starts and
    cannot already be over.
    """
    starts_at = forms.SplitDateTimeField(label="Starts", widget=DateAndHourWidget)
    ends_at = forms.SplitDateTimeField(label="Ends", widget=DateAndHourWidget)

    class Meta:
        model = Shift
        fields = ["solver", "starts_at", "ends_at"]

    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["solver"].queryset = User.objects.filter(
            teammember__team=team, role="solver", is_active=True).order_by("first_name", "last_name")
        self.fields["solver"].label_from_instance = lambda u: f"{u.first_name} {u.last_name}"

    def clean(self):
        data = super().clean()
        starts_at, ends_at = data.get("starts_at"), data.get("ends_at")
        if starts_at and ends_at and ends_at <= starts_at:
            self.add_error("ends_at", "The shift ends before it starts")
        elif ends_at and ends_at <= timezone.now():
            self.add_error("ends_at", "That shift is already over. Shifts can only be added for the future.")
        return data
