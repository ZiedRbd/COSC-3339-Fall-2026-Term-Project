// Confirmation modal before a shift is saved
const sModal = document.getElementById("shift-modal");
if (sModal) {
  const sText = document.getElementById("shift-modal-text");
  let sForm = null;
  const value = (form, name) => {
    const el = form.querySelector("[name=" + name + "]");
    return el ? el.value : "";
  };
  // "Thu, Oct 22 16:00" from the date picker and the 24-hour dropdown
  const when = (day, hour) => {
    if (!day || !hour) return "?";
    const date = new Date(day + "T" + hour).toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
    return date + " " + hour;
  };

  document.querySelectorAll(".shift-form").forEach(form => {
    form.addEventListener("submit", e => {
      e.preventDefault();
      sForm = form;
      const who = form.querySelector("select[name=solver]");
      const name = who && who.selectedIndex >= 0 ? who.options[who.selectedIndex].text : "?";
      sText.textContent = name + ": " + when(value(form, "starts_at_0"), value(form, "starts_at_1"))
        + " to " + when(value(form, "ends_at_0"), value(form, "ends_at_1"));
      sModal.hidden = false;
    });
  });

  document.getElementById("shift-cancel").addEventListener("click", () => {
    sModal.hidden = true;
    sForm = null;
  });

  // form.submit() does not re-fire the submit listener, so this saves the shift
  document.getElementById("shift-confirm").addEventListener("click", () => {
    if (sForm) sForm.submit();
  });

  sModal.addEventListener("click", e => {
    if (e.target === sModal) sModal.hidden = true;
  });
}
