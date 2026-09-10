from django import forms 
from .models import User

# What a new user must fill in to register
class RegisterForm(forms.Form):
    first_name = forms.CharField(max_length=50)
    last_name = forms.CharField(max_length=50)
    email = forms.EmailField()
    password = forms.CharField(min_length=8)
    password2 = forms.CharField(min_length=8, label="Confirm password")
    
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
