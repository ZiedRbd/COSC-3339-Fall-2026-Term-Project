// Confirmation modal for status transitions
const tModal = document.getElementById("transition-modal");
if (tModal) {
  const tTitle = document.getElementById("transition-title");
  let tForm = null;

  document.querySelectorAll(".transition-form").forEach(form => {
    form.addEventListener("submit", e => {
      e.preventDefault();
      tForm = form;
      tTitle.textContent = "Move this ticket to " + form.dataset.label + "?";
      tModal.hidden = false;
    });
  });

  document.getElementById("transition-cancel").addEventListener("click", () => {
    tModal.hidden = true;
    tForm = null;
  });

  // form.submit() does not re-fire the submit listener, so this sends the move
  document.getElementById("transition-confirm").addEventListener("click", () => {
    if (tForm) tForm.submit();
  });

  tModal.addEventListener("click", e => {
    if (e.target === tModal) tModal.hidden = true;
  });
}
