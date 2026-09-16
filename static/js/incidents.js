// Delete confirmation modal on the incident list
const modal = document.getElementById("confirm-modal");
const titleEl = document.getElementById("confirm-title");
let pendingForm = null;

document.querySelectorAll(".delete-form button").forEach(btn => {
  btn.addEventListener("click", () => {
    pendingForm = btn.closest("form");
    titleEl.textContent = btn.dataset.title;
    modal.hidden = false;
  });
});

document.getElementById("confirm-cancel").addEventListener("click", () => {
  modal.hidden = true;
  pendingForm = null;
});

document.getElementById("confirm-delete").addEventListener("click", () => {
  if (pendingForm) pendingForm.submit();
});

modal.addEventListener("click", e => {
  if (e.target === modal) modal.hidden = true;
});
