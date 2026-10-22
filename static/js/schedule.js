// The shift form sits in a popup. "Add shift" opens it empty, "Edit" opens it
// filled in with that shift, and the server reopens it when a save is refused.
const formModal = document.getElementById("shift-form-modal");
if (formModal) {
  const shiftForm = formModal.querySelector("form");
  const formTitle = document.getElementById("shift-form-title");
  const formSubmit = document.getElementById("shift-form-submit");
  const field = name => shiftForm.querySelector("[name=" + name + "]");
  const show = (action, title, button) => {
    shiftForm.action = action;
    formTitle.textContent = title;
    formSubmit.textContent = button;
    formModal.hidden = false;
  };

  document.getElementById("add-shift").addEventListener("click", () => {
    field("solver").selectedIndex = 0;
    field("starts_at_0").value = "";
    field("starts_at_1").value = "00:00";
    field("ends_at_0").value = "";
    field("ends_at_1").value = "00:00";
    show(formModal.dataset.addUrl, "Add a shift", "Add shift");
  });

  document.querySelectorAll(".shift-edit").forEach(link => {
    link.addEventListener("click", e => {
      e.preventDefault();
      field("solver").value = link.dataset.solver;
      field("starts_at_0").value = link.dataset.startDate;
      field("starts_at_1").value = link.dataset.startHour;
      field("ends_at_0").value = link.dataset.endDate;
      field("ends_at_1").value = link.dataset.endHour;
      show(link.getAttribute("href"), "Edit shift", "Save changes");
    });
  });

  document.getElementById("shift-form-cancel").addEventListener("click", () => {
    formModal.hidden = true;
  });
  formModal.addEventListener("click", e => {
    if (e.target === formModal) formModal.hidden = true;
  });
}

// Confirmation before a shift is saved
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
