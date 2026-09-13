function togglePasswordVisibility() {
    const pass1 = document.getElementById("id_password1") || document.getElementById("id_password");
    const pass2 = document.getElementById("id_password2");
    const toggleBtn = document.getElementById("togglePasswordBtn");
    const isPassType = pass1.type === "password"

    const isPassword = pass1.type === "password";
    const newType = isPassword ? "text" : "password";

    // Toggle the first password field
    pass1.type = newType;

    // Toggle the second password field if it exists on this page (Registration page)
    if (pass2) {
        pass2.type = newType;
    }

    // Update button text
    toggleBtn.textContent = isPassword ? "Hide" : "Show";
}