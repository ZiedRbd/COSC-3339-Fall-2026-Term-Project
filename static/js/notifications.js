document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("notificationBtn");
    const dropdown = document.getElementById("notificationDropdown");
    if (!btn || !dropdown) return;

    function setOpen(open) {
        dropdown.classList.toggle("active", open);
        btn.setAttribute("aria-expanded", open ? "true" : "false");
    }

    btn.addEventListener("click", function (e) {
        e.stopPropagation();
        setOpen(!dropdown.classList.contains("active"));
    });

    document.addEventListener("click", function (e) {
        if (!dropdown.contains(e.target) && !btn.contains(e.target)) setOpen(false);
    });

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape" && dropdown.classList.contains("active")) {
            setOpen(false);
            btn.focus();
        }
    });

    function line(className, text) {
        const span = document.createElement("span");
        span.className = className;
        span.textContent = text;
        return span;
    }

    function capitalised(text) {
        return text.charAt(0).toUpperCase() + text.slice(1);
    }

    // A solver's message reads "Ticket #6 (Power Outlets, medium) what happened. What to do."
    // The number is already on the stub, so the service and severity get a line of their own
    // and the rest follows as one quiet sentence. When what happened only repeats the heading
    // ("Assigned to you" over "was assigned to you"), it is said once, in the heading.
    // A message worded any other way is left as it is.
    const SOLVER_MESSAGE = /^Ticket #\d+ \(([^()]+), (low|medium|high|critical)\) ([\s\S]+)$/;
    dropdown.querySelectorAll(".notification-item").forEach(function (item) {
        const text = item.querySelector(".notification-text");
        const kind = item.querySelector(".notification-kind");
        const match = text ? text.textContent.trim().match(SOLVER_MESSAGE) : null;
        if (!match) return;
        const service = match[1], severity = match[2], rest = match[3];
        const cut = rest.indexOf(". ");
        const what = cut === -1 ? rest : rest.slice(0, cut + 1);
        const todo = cut === -1 ? "" : rest.slice(cut + 2);

        let detail = capitalised(what) + (todo ? " " + todo : "");
        const said = capitalised(what.replace(/^was /, "").replace(/\.$/, ""));
        if (kind && said.toLowerCase().indexOf(kind.textContent.trim().toLowerCase()) === 0) {
            kind.textContent = said;
            detail = todo;
        }

        const meta = line("notification-meta", "");
        meta.append(line("notification-service", service),
                    line("notification-sev sev-" + severity, capitalised(severity)));
        text.textContent = "";
        text.append(meta);
        if (detail) text.append(line("notification-detail", detail));
    });

    // "36 min ago" reads faster than a date. The date stays as the tooltip,
    // and anything older than a week keeps the date the server printed.
    function ago(then) {
        const minutes = Math.round((Date.now() - then.getTime()) / 60000);
        if (minutes < 1) return "Just now";
        if (minutes < 60) return minutes + " min ago";
        const hours = Math.round(minutes / 60);
        if (hours < 24) return hours + " h ago";
        const days = Math.round(hours / 24);
        if (days < 7) return days === 1 ? "Yesterday" : days + " days ago";
        return null;
    }
    dropdown.querySelectorAll("time.notification-time").forEach(function (time) {
        const then = new Date(time.getAttribute("datetime"));
        if (isNaN(then.getTime())) return;
        const words = ago(then);
        if (words) {
            time.title = time.textContent.trim();
            time.textContent = words;
        }
    });
});
