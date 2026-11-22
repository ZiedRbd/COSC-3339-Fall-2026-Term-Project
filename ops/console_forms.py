"""The forms the administrator console shows in its dialog."""
from django import forms

from .forms import RegisterForm
from .json_settings import SETTINGS, password_rules_sentence
from .models import Building, Incident, Service, Team, TeamMember, User
from .overrides import HELD

ROLES = [("reporter", "Reporter"), ("solver", "Solver"), ("auditor", "Auditor")]
CRITICALITIES = [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("critical", "Critical")]
INPUT = {"class": "form-input"}
ACCOUNTS = SETTINGS["accounts"]


def full_name(user):
    return f"{user.first_name} {user.last_name}".strip() or user.email


class SolverChoiceField(forms.ModelChoiceField):
    """A dropdown of people, shown by their full name."""

    def label_from_instance(self, user):
        return full_name(user)


class UserForm(forms.Form):
    """A new account, or a change to one. The password is only asked for when the account is new or it is being reset."""
    first_name = forms.CharField(min_length=ACCOUNTS["name_min_characters"], max_length=ACCOUNTS["name_max_characters"],
                                 widget=forms.TextInput(attrs=INPUT))
    last_name = forms.CharField(min_length=ACCOUNTS["name_min_characters"], max_length=ACCOUNTS["name_max_characters"],
                                 widget=forms.TextInput(attrs=INPUT))
    email = forms.EmailField(max_length=150, widget=forms.EmailInput(attrs=INPUT))
    role = forms.ChoiceField(choices=ROLES, widget=forms.Select(attrs=INPUT))
    password = forms.CharField(required=False, widget=forms.PasswordInput(attrs={**INPUT, "autocomplete": "new-password"}))

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        if user is None:
            self.fields["password"].help_text = password_rules_sentence()
        else:
            self.fields["password"].label = "New password"
            self.fields["password"].help_text = "Leave this empty to keep the current password."
            self.initial.update(first_name=user.first_name, last_name=user.last_name, email=user.email, role=user.role)

    def clean_email(self):
        email = self.cleaned_data["email"].lower()
        taken = User.objects.filter(email=email)
        if self.user is not None:
            taken = taken.exclude(pk=self.user.pk)
        if taken.exists():
            raise forms.ValidationError("This email is already registered")
        return email

    def clean_password(self):
        password = self.cleaned_data.get("password", "")
        if not password:
            if self.user is None:
                raise forms.ValidationError("A new account needs a password")
            return ""
        if len(password) < ACCOUNTS["password_min_characters"]:
            raise forms.ValidationError(f"Password needs at least {ACCOUNTS['password_min_characters']} characters")
        # The same rules an account has when somebody registers
        return RegisterForm.clean_password(self)

    def clean_role(self):
        role = self.cleaned_data["role"]
        user = self.user
        if user is not None and user.role == "solver" and role != "solver":
            if Team.objects.filter(lead=user, is_active=True).exists():
                raise forms.ValidationError("This solver leads a team. Appoint a new lead first.")
            if TeamMember.objects.filter(user=user, team__is_active=True).exists():
                raise forms.ValidationError("This solver is on a team. Take them off every team first.")
            if Incident.objects.filter(assigned_to=user, status__in=HELD, is_deleted=False).exists():
                raise forms.ValidationError("This solver holds unfinished tickets. Reassign them first.")
        return role

    def save(self):
        fields = {name: self.cleaned_data[name] for name in ("first_name", "last_name", "email", "role")}
        if self.user is None:
            return User.objects.create_user(username=fields["email"], password=self.cleaned_data["password"], **fields)
        for name, value in fields.items():
            setattr(self.user, name, value)
        self.user.username = fields["email"]
        if self.cleaned_data["password"]:
            self.user.set_password(self.cleaned_data["password"])
        self.user.save()
        return self.user


class TeamForm(forms.Form):
    """A new team with its lead, or a new name and description for a team. The lead is changed from the members dialog."""
    name = forms.CharField(max_length=100, widget=forms.TextInput(attrs=INPUT))
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={**INPUT, "rows": 3}))
    lead = SolverChoiceField(queryset=User.objects.none(), empty_label="Choose a solver", widget=forms.Select(attrs=INPUT))

    def __init__(self, *args, team=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        if team is None:
            self.fields["lead"].queryset = User.objects.filter(role="solver", is_active=True).order_by("first_name", "last_name")
        else:
            del self.fields["lead"]
            self.initial.update(name=team.name, description=team.description)

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        same = Team.objects.filter(name__iexact=name)
        if self.team is not None:
            same = same.exclude(pk=self.team.pk)
        if same.filter(is_active=True).exists():
            raise forms.ValidationError("A team already has this name")
        if same.exists():
            raise forms.ValidationError("A removed team has this name. Restore it from the Removed tab.")
        return name


class ServiceForm(forms.Form):
    """A new service, or a change to one."""
    name = forms.CharField(max_length=100, widget=forms.TextInput(attrs=INPUT))
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={**INPUT, "rows": 3}))
    owning_team = forms.ModelChoiceField(queryset=Team.objects.none(), label="Team", empty_label="Choose a team",
                                         widget=forms.Select(attrs=INPUT))
    criticality = forms.ChoiceField(choices=CRITICALITIES, initial="medium", widget=forms.Select(attrs=INPUT))

    def __init__(self, *args, service=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = service
        self.fields["owning_team"].queryset = Team.objects.filter(is_active=True).order_by("name")
        if service is not None:
            self.initial.update(name=service.name, description=service.description,
                                owning_team=service.owning_team_id, criticality=service.criticality)

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        same = Service.objects.filter(name__iexact=name, is_active=True)
        if self.service is not None:
            same = same.exclude(pk=self.service.pk)
        if same.exists():
            raise forms.ValidationError("A service already has this name")
        return name

    def clean_owning_team(self):
        team = self.cleaned_data["owning_team"]
        service = self.service
        if service is not None and service.owning_team_id != team.pk:
            unfinished = Incident.objects.filter(service=service, is_deleted=False).exclude(status__in=("resolved", "closed"))
            if unfinished.exists():
                raise forms.ValidationError(
                    "This service has unfinished tickets with its team. Finish them first, or move all of the "
                    "team's services from the Teams tab.")
        return team

    def save(self):
        service = self.service or Service()
        for name in ("name", "description", "owning_team", "criticality"):
            setattr(service, name, self.cleaned_data[name])
        service.save()
        return service


class BuildingForm(forms.Form):
    """A new building for the ticket form, or a change to one."""
    name = forms.CharField(max_length=100, widget=forms.TextInput(attrs=INPUT))
    aliases = forms.CharField(required=False, max_length=200, label="Short names",
                              help_text="Other names people use for it, separated by commas.",
                              widget=forms.TextInput(attrs=INPUT))
    kind = forms.ChoiceField(choices=Building.KIND_CHOICES, widget=forms.Select(attrs=INPUT))

    def __init__(self, *args, building=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.building = building
        if building is not None:
            self.initial.update(name=building.name, aliases=building.aliases, kind=building.kind)

    def clean_name(self):
        name = " ".join(self.cleaned_data["name"].split())
        same = Building.objects.filter(name__iexact=name)
        if self.building is not None:
            same = same.exclude(pk=self.building.pk)
        if same.filter(is_active=True).exists():
            raise forms.ValidationError("A building already has this name")
        if same.exists():
            raise forms.ValidationError("A removed building has this name. Restore it from the Removed tab.")
        return name

    def save(self):
        building = self.building or Building()
        for name in ("name", "aliases", "kind"):
            setattr(building, name, self.cleaned_data[name])
        building.save()
        return building
