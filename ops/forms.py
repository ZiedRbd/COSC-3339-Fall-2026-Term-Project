from django import forms 
from .models import User, Service

# What a new user must fill in to register
class RegisterForm(forms.Form):
    first_name = forms.CharField(max_length=50,
                                 widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'First name'})
                                 )
    last_name = forms.CharField(max_length=50,
                                 widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Last name'})
                                 )
    email = forms.EmailField(widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Email'}))
    password = forms.CharField(min_length=8,
                               widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Password'}))
    password2 = forms.CharField(min_length=8,
                                widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Confirm Password'}))
    
    def clean_password(self):
        pw = self.cleaned_data["password"]
        if not any(c.isupper() for c in pw):
            raise forms.ValidationError("Password needs an uppercase letter")
        if not any(c.islower() for c in pw):
            raise forms.ValidationError("Password needs a lowercase letter")
        if not any(c.isdigit() for c in pw):
            raise forms.ValidationError("Password needs a number")
        if not any(not c.isalnum() for c in pw):
            raise forms.ValidationError("Password needs a symbol")
        return pw

    # Runs after all fields pass. Checks the two passwords match.
    def clean(self):
        data = super().clean()
        pw, pw2 = data.get("password"), data.get("password2")
        if pw and pw2 and pw != pw2:
            self.add_error("password2", "Passwords do not match")
        return data

    # Rejects an email that is already registered
    def clean_email(self):
        email = self.cleaned_data["email"]
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("This email is already registered")
        return email


#ian
class IncidentForm(forms.Form):
    title = forms.CharField(
        max_length=200, # Matched to Incident model's max_length=200
        widget=forms.TextInput(attrs={'class': 'form-input', 'placeholder': 'Brief title'})
    )
    description = forms.CharField(
        widget=forms.Textarea(attrs={'class': 'form-input text-field', 'rows': 4}) # Renders a text box instead of a single-line input
    )

    # Pulls all services available in database for selection
    service = forms.ModelChoiceField(
        queryset=Service.objects.all(),
        empty_label="Select a service"
    )




