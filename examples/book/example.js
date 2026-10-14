// Loaded (deferred) by every page (extra_js in html_config.json). Adds a button to go back to the top.
document.addEventListener("DOMContentLoaded", function () {
    const button = document.createElement("button");
    button.className = "back-to-top";
    button.textContent = "↑ Top";
    button.addEventListener("click", () => window.scrollTo({top: 0, behavior: "smooth"}));
    document.body.appendChild(button);
});
