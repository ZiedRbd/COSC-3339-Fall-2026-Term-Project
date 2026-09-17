// Show/hide toggle for the password fields. Called from the Show button.
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
// Same five rules as clean_password in forms.py plus a match check.
// Watches both password boxes. Server still validates on submit.
(function () {
    const pw1 = document.getElementById("id_password1") || document.getElementById("id_password");
    const pw2 = document.getElementById("id_password2");
    const list = document.querySelector(".pw-rules");
    if (!pw1 || !list) return;

    const rules = {
        length: pw => pw.length >= 8,
        upper:  pw => /[A-Z]/.test(pw),
        lower:  pw => /[a-z]/.test(pw),
        digit:  pw => /[0-9]/.test(pw),
        symbol: pw => /[^A-Za-z0-9]/.test(pw),
        match:  pw => pw.length > 0 && pw2 && pw === pw2.value,
    };

    function update() {
        const pw = pw1.value;
        list.querySelectorAll("li[data-rule]").forEach(li => {
            const check = rules[li.dataset.rule];
            if (!check) return;
            const ok = !!check(pw);
            li.classList.toggle("ok", ok);
            const mark = li.querySelector(".mark");
            if (mark) mark.textContent = ok ? "✓" : "✗";
        });
    }

    pw1.addEventListener("input", update);
    if (pw2) pw2.addEventListener("input", update);
    update();
})();
