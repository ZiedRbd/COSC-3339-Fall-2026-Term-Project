function togglePasswordVisibility() {
    const pass1 = document.getElementById("id_password1") || document.getElementById("id_password");
    const pass2 = document.getElementById("id_password2");
    const toggleBtn = document.getElementById("togglePasswordBtn");

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


// Live password checklist on the registration page.
// Same five rules as clean_password in forms.py. Server still validates.
document.addEventListener("DOMContentLoaded", () => {
    const input = document.getElementById("id_password1") || document.getElementById("id_password");
    const list = document.querySelector(".pw-rules");
    if (!input || !list) return;

    const rules = {
        length: pw => pw.length >= 8,
        upper:  pw => /[A-Z]/.test(pw),
        lower:  pw => /[a-z]/.test(pw),
        digit:  pw => /[0-9]/.test(pw),
        symbol: pw => /[^A-Za-z0-9]/.test(pw),
    };

    input.addEventListener("input", () => {
        const pw = input.value;
        list.querySelectorAll("li").forEach(li => {
            li.classList.toggle("ok", rules[li.dataset.rule](pw));
        });
    });
});
