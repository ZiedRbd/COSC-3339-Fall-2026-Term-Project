function togglePasswordVisibility() {
    const passwordInput = document.getElementById("id_password");
    const toggleBtn = document.getElementById("togglePasswordBtn");

    if (passwordInput.type === "password") {
        passwordInput.type = "text";
        toggleBtn.textContent = "Hide";
    } else {
        passwordInput.type = "password";
        toggleBtn.textContent = "Show";
    }
}