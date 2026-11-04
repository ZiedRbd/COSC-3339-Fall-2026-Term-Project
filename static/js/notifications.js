document.addEventListener("DOMContentLoaded", function () {
    const btn = document.getElementById("notificationBtn");
    const dropdown = document.getElementById("notificationDropdown");

    if (btn && dropdown) {
        btn.addEventListener("click", function (e) {
            e.stopPropagation();
            dropdown.classList.toggle("active");
        });

        document.addEventListener("click", function (e) {
            if (!dropdown.contains(e.target) && e.target !== btn) {
                dropdown.classList.remove("active");
            }
        });
    }
});