"use strict";

// Runs on the OnlyBrowserOS start page only. A local file page cannot open an
// extension page by itself, so this script shows the Settings button, handles
// its click, and opens Settings when someone searches for "settings".

const openSettings = () => browser.runtime.sendMessage({ type: "open-settings" });

const settingsButton = document.getElementById("settings");
if (settingsButton) {
  settingsButton.hidden = false;
  settingsButton.addEventListener("click", openSettings);
}

const SETTINGS_WORDS = new Set(["settings", "setting", "onlybrowseros settings", "control panel"]);
const searchForm = document.querySelector("form.search");
if (searchForm) {
  searchForm.addEventListener("submit", (event) => {
    const box = document.getElementById("q");
    if (box && SETTINGS_WORDS.has(box.value.trim().toLowerCase())) {
      event.preventDefault();
      openSettings();
    }
  }, true);
}
