document.addEventListener("DOMContentLoaded", () => {
    const container = document.querySelector(".zip-checker-container");
    if (!container) return; // shortcode not on this page

    const formZipEl = container.querySelector("#formZip");
    const feedbackEl = container.querySelector("#feedback");
    const loginlinkEl = container.querySelector("#loginlink");
    const warningEl = container.querySelector("#warning");
    const clearEl = container.querySelector("#clear");

    if (!formZipEl) return;

    formZipEl.addEventListener("input", () => {
        const zip = formZipEl.value;

        fetch(zipChecker.ajaxUrl, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action: "check_zip", zip })
        })
        .then(res => res.json())
        .then(data => {
            feedbackEl.textContent = data.message || "";
            warningEl.textContent = data.warning || "";
            if (data.link) {
                loginlinkEl.href = data.link;
                loginlinkEl.textContent = data.linkText;
            } else {
                loginlinkEl.href = "";
                loginlinkEl.textContent = "";
            }
        });
    });

    clearEl.addEventListener("click", () => {
        formZipEl.value = "";
        feedbackEl.textContent = "";
        loginlinkEl.textContent = "";
        loginlinkEl.href = "";
        warningEl.textContent = "";
    });
	});