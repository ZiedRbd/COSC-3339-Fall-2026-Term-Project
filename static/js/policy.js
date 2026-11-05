// The tier form shows only the fields that matter for the chosen target:
// the solver dropdown only for "a named solver", and no wait for administration.
document.addEventListener("DOMContentLoaded", function () {
    const kind = document.getElementById("id_escalate_to");
    const solverRow = document.getElementById("id_escalate_to_user").closest("p");
    const waitInput = document.getElementById("id_wait_minutes");
    const waitRow = waitInput.closest("p");
    if (!kind) return;

    function refresh() {
        solverRow.hidden = kind.value !== "user";
        waitRow.hidden = kind.value === "administration";
        if (kind.value === "administration") waitInput.value = "";
    }

    kind.addEventListener("change", refresh);
    refresh();
});
