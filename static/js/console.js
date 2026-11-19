// The administrator console: its tabs, the row filter, and the one dialog
// every action opens in. The dialog's content comes from the server, so a
// form with a mistake comes back into the same dialog with its errors.
(function () {
    const overlay = document.getElementById("console-dialog");
    if (!overlay) return;
    const box = overlay.querySelector(".modal");
    let changed = false;

    function fail() {
        box.innerHTML = '<p class="notice error">That did not go through. Close this and try again.</p>' +
            '<div class="actions"><button type="button" class="btn-small" data-close>Close</button></div>';
        overlay.hidden = false;
    }

    async function show(url, options) {
        box.setAttribute("aria-busy", "true");
        let response;
        try {
            response = await fetch(url, Object.assign({ credentials: "same-origin" }, options));
        } catch (error) {
            fail();
            return;
        } finally {
            box.removeAttribute("aria-busy");
        }
        // The server says the work is done: load the page again so every tab shows it
        if (response.headers.get("X-Console-Done")) {
            window.location.reload();
            return;
        }
        if (!response.ok) {
            fail();
            return;
        }
        box.innerHTML = await response.text();
        box.scrollTop = 0;
        overlay.hidden = false;
        const first = box.querySelector("input:not([type=hidden]), select, textarea");
        if (first) first.focus();
    }

    function close() {
        overlay.hidden = true;
        box.innerHTML = "";
        if (changed) window.location.reload();
    }

    document.addEventListener("click", function (event) {
        const opener = event.target.closest("[data-dialog]");
        if (opener) {
            event.preventDefault();
            show(opener.dataset.dialog);
            return;
        }
        if (event.target.closest("[data-close]") || event.target === overlay) close();
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape" && !overlay.hidden) close();
    });

    box.addEventListener("submit", function (event) {
        event.preventDefault();
        changed = true;
        show(event.target.action, { method: "POST", body: new FormData(event.target, event.submitter) });
    });

    // Tabs: the address remembers the open one, so a reload comes back to it
    const tabs = document.querySelectorAll("[data-tab]");
    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            tabs.forEach(function (other) {
                const open = other === tab;
                other.setAttribute("aria-selected", open ? "true" : "false");
                document.getElementById("panel-" + other.dataset.tab).hidden = !open;
            });
            const address = new URL(window.location);
            address.searchParams.set("tab", tab.dataset.tab);
            window.history.replaceState(null, "", address);
        });
    });

    // Filter: hide the rows that do not have the typed words in them
    document.querySelectorAll("[data-filter]").forEach(function (input) {
        input.addEventListener("input", function () {
            const words = input.value.trim().toLowerCase();
            input.closest(".console-panel").querySelectorAll("tbody tr").forEach(function (row) {
                row.hidden = words !== "" && !row.textContent.toLowerCase().includes(words);
            });
        });
    });
})();
