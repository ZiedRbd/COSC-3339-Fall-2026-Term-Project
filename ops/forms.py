from django import forms
from django.utils import timezone

from .models import EscalationTier, Service, Shift, User


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
        max_length=150,
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
        max_length=80,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Brief title'})
    )
    description = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input text-field', 'rows': 4})
    )

    # Optional location details
    building = forms.CharField(
        max_length=40,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Building (optional)'})
    )
    room = forms.CharField(
        max_length=20,
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
    One on-call shift for a team, primary or secondary. The solver list
    only offers active solvers who are on that team. A shift must end
    after it starts and cannot already be over. The role is chosen when
    the shift is added and stays fixed when it is edited.
    """
    starts_at = forms.SplitDateTimeField(label="Starts", widget=DateAndHourWidget)
    ends_at = forms.SplitDateTimeField(label="Ends", widget=DateAndHourWidget)

    class Meta:
        model = Shift
        fields = ["on_call_role", "solver", "starts_at", "ends_at"]
        labels = {"on_call_role": "Role"}
        help_texts = {"on_call_role": "Primary is required around the clock. Secondary is optional "
                                      "and takes tickets once the primary holds 3."}

    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Left out, a shift is primary. An existing shift keeps its role.
        self.fields["on_call_role"].required = False
        self.fields["on_call_role"].disabled = bool(self.instance.pk)
        self.fields["solver"].queryset = User.objects.filter(
            teammember__team=team, role="solver", is_active=True).order_by("first_name", "last_name")
        self.fields["solver"].label_from_instance = lambda u: f"{u.first_name} {u.last_name}"

    def clean_on_call_role(self):
        return self.cleaned_data.get("on_call_role") or "primary"

    def clean(self):
        data = super().clean()
        starts_at, ends_at = data.get("starts_at"), data.get("ends_at")
        if not (starts_at and ends_at):
            return data
        # A shift may begin in the hour that is running now, not earlier. A shift
        # that already started keeps its start when the lead edits something else.
        this_hour = timezone.now().replace(minute=0, second=0, microsecond=0)
        original_start = self.instance.starts_at if self.instance.pk else None
        if ends_at <= starts_at:
            self.add_error("ends_at", "The shift ends before it starts")
        elif ends_at <= timezone.now():
            self.add_error("ends_at", "That shift is already over. Shifts can only be added for the future.")
        elif starts_at < this_hour and starts_at != original_start:
            self.add_error("starts_at", "A shift cannot start in the past")
        return data


MAX_TIER_WAIT = 1440
WAIT_ERROR = f"Wait must be a whole number of minutes above zero, and at most {MAX_TIER_WAIT} (one day)"
TARGET_ERROR = "Pick the team lead or an active solver on this team"


class EscalationTierForm(forms.ModelForm):
    """
    One step of a team's escalation policy: who gets the ticket and how
    many minutes they have. Tier 1 is always the on-call solver, so its
    form has only the wait. A later tier picks the team lead (a role) or
    one active solver on the team (a user) from a single list. Whatever
    is wrong with the wait gets the same one sentence.
    """
    target = forms.ChoiceField(label="Escalate to", error_messages={"required": TARGET_ERROR})
    wait_minutes = forms.IntegerField(
        label="Wait (minutes)", min_value=1, max_value=MAX_TIER_WAIT,
        error_messages={key: WAIT_ERROR for key in ("required", "invalid", "min_value", "max_value")},
    )
    field_order = ["target", "wait_minutes"]

    class Meta:
        model = EscalationTier
        fields = ["wait_minutes"]

    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        tier = self.instance
        # Let the server, not the browser, explain why -2 is refused
        for limit in ("min", "max"):
            self.fields["wait_minutes"].widget.attrs.pop(limit, None)
        if tier.pk:
            # A saved tier is edited in its table row, by the form with this id
            for field in self.fields.values():
                field.widget.attrs["form"] = f"tier-{tier.pk}"
        if tier.pk and tier.tier_number == 1:
            del self.fields["target"]
            return
        lead = f"Team lead ({team.lead.first_name} {team.lead.last_name})" if team.lead else "Team lead"
        choices = [("lead", lead)]
        for person in User.objects.filter(teammember__team=team, role="solver", is_active=True).order_by(
                "first_name", "last_name"):
            choices.append((f"user:{person.pk}", f"{person.first_name} {person.last_name}"))
        if tier.pk and tier.escalate_to == "lead":
            self.initial["target"] = "lead"
        elif tier.pk and tier.escalate_to_user is not None:
            current = f"user:{tier.escalate_to_user_id}"
            if current not in dict(choices):
                # Left the team or was deactivated since: the tier is skipped until it is changed
                gone = tier.escalate_to_user
                choices.append((current, f"{gone.first_name} {gone.last_name} (not available, tier is skipped)"))
            self.initial["target"] = current
        self.fields["target"].choices = choices
        self.fields["target"].error_messages["invalid_choice"] = TARGET_ERROR

    def clean_wait_minutes(self):
        # "1_0", "+5" and "5.0" all read as numbers to Python. Only plain digits are a whole number here.
        typed = str(self.data.get(self.add_prefix("wait_minutes"), "")).strip()
        if not (typed.isascii() and typed.isdigit()):
            raise forms.ValidationError(WAIT_ERROR)
        return self.cleaned_data["wait_minutes"]

    def save(self, commit=True):
        tier = super().save(commit=False)
        target = self.cleaned_data.get("target")
        if target == "lead":
            tier.escalate_to, tier.escalate_to_user = "lead", None
        elif target:
            tier.escalate_to, tier.escalate_to_user_id = "user", int(target.split(":")[1])
        if commit:
            tier.save()
        return tier
