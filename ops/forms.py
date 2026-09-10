from django import forms 


# What a new user must fill in to register
class RegisterForm(forms.Form):
    first_name = forms.CharField(max_length=50)
    last_name = forms.CharField(max_length=50)
    email = forms.EmailField()
    password = forms.CharField(min_length=8)
    password2 = forms.CharField(min_length=8)
    
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

