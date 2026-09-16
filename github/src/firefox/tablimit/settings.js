"use strict";

// OnlyBrowserOS settings page. Everything is read and saved through the
// extension's background script, which asks /usr/lib/onlybrowseros/settings-host.
// Keep the levels and thresholds in step with src/shared/levels.py.

const LEVELS = [
  { key: "low", name: "Low-end PC", text: "Older or budget computer", angle: 205 },
  { key: "mid", name: "Mid-range PC", text: "Everyday computer", angle: 270 },
  { key: "high", name: "High-end PC", text: "Fast, newer computer", angle: 335 },
];
const LEVEL_ORDER = LEVELS.map((l) => l.key);
const TEXT_SIZES = [
  { key: "normal", name: "Normal", scale: 1 },
  { key: "large", name: "Large", scale: 1.25 },
  { key: "larger", name: "Larger", scale: 1.5 },
];

const recommendedLevel = (mb) => (mb < 3000 ? "low" : mb < 6500 ? "mid" : "high");
const tabsFor = (level, mb) => (level === "low" ? (mb < 1500 ? 1 : 2) : level === "mid" ? 4 : 8);
const levelFor = (limit, automatic, mb) =>
  automatic ? recommendedLevel(mb) : limit <= 2 ? "low" : limit <= 4 ? "mid" : "high";
const tabsText = (n) => `up to ${n} tab${n === 1 ? "" : "s"}`;
const $ = (id) => document.getElementById(id);

let settings = null;
const chosen = { level: null, size: null };

function ask(request) {
  return browser.runtime.sendMessage({ type: "system", request })
    .catch(() => null)
    .then((reply) => reply || { ok: false, error: "Could not reach the settings." });
}

function setNote(id, text, kind) {
  const note = $(id);
  note.textContent = text || "";
  note.className = "note" + (kind ? " " + kind : "");
}

async function save(buttonId, noteId, request, success) {
  const button = $(buttonId);
  button.disabled = true;
  setNote(noteId, "Saving…");
  const reply = await ask(request);
  if (reply.ok) {
    Object.assign(settings, reply);
    setNote(noteId, success(reply), "good");
    return true;
  }
  button.disabled = false;
  setNote(noteId, reply.error || "Could not save.", "error");
  return false;
}

function choice(checked, parts, onClick) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "choice";
  button.setAttribute("role", "radio");
  button.setAttribute("aria-checked", String(checked));
  button.append(...parts);
  button.addEventListener("click", onClick);
  return button;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

// ------------------------------------------------------------ power

function gaugeSvg(angle) {
  const r = (angle * Math.PI) / 180;
  const x = (12 + 7 * Math.cos(r)).toFixed(2);
  const y = (14.5 + 7 * Math.sin(r)).toFixed(2);
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" aria-hidden="true">` +
    `<path d="M3.07 17.75A9.5 9.5 0 1 1 20.93 17.75"/><path d="M12 14.5L${x} ${y}"/>` +
    `<circle cx="12" cy="14.5" r="2.3" fill="currentColor" stroke="none"/></svg>`;
}

function renderPower() {
  const memory = settings.memory_mb;
  const saved = levelFor(settings.tab_limit, settings.limit_is_automatic, memory);
  const recommended = recommendedLevel(memory);
  const box = $("levels");
  box.textContent = "";
  for (const level of LEVELS) {
    const badge = el("span", "badge");
    badge.innerHTML = gaugeSvg(level.angle);
    const words = el("span", "words");
    words.append(el("strong", "", level.name), el("span", "", `${level.text} · ${tabsText(tabsFor(level.key, memory))} at once`));
    const parts = [el("span", "dot"), badge, words];
    if (level.key === recommended) parts.push(el("span", "chip", "Recommended"));
    box.append(choice(level.key === chosen.level, parts, () => {
      chosen.level = level.key;
      renderPower();
    }));
  }
  $("power-save").disabled = chosen.level === saved;
  if (chosen.level !== saved && LEVEL_ORDER.indexOf(chosen.level) > LEVEL_ORDER.indexOf(recommended)) {
    setNote("power-note", "With this much memory, websites may be slow at this level, and tabs may close by themselves when memory runs out.", "warn");
  } else if (chosen.level !== saved) {
    setNote("power-note", "");
  }
}

$("power-save").addEventListener("click", async () => {
  const memory = settings.memory_mb;
  const value = chosen.level === recommendedLevel(memory) ? "auto" : String(tabsFor(chosen.level, memory));
  const n = tabsFor(chosen.level, memory);
  if (await save("power-save", "power-note", { cmd: "set-tabs", value },
    () => `Saved. From now on ${tabsText(n)} can stay open at once.`)) {
    renderPower();
  }
});

// ------------------------------------------------------------ text size

function renderSizes() {
  const box = $("sizes");
  box.textContent = "";
  for (const size of TEXT_SIZES) {
    const sample = el("span", "sample", "Aa");
    sample.style.fontSize = `${Math.round(22 * size.scale)}px`;
    box.append(choice(size.key === chosen.size, [sample, el("span", "", size.name)], () => {
      chosen.size = size.key;
      renderSizes();
    }));
  }
  $("text-save").disabled = chosen.size === settings.text_size;
}

$("text-save").addEventListener("click", () => {
  save("text-save", "text-note", { cmd: "set-text-size", value: chosen.size },
    () => "Saved. The browser starts again in a moment to show the new size. Your tabs come back.");
});

// ------------------------------------------------------------ time zone

function fillCities(region, selected) {
  const city = $("city");
  city.textContent = "";
  city.disabled = region === "UTC";
  for (const name of settings.timezones[region] || []) {
    const option = el("option", "", name.replace(/_/g, " ").replace(/\//g, " / "));
    option.value = name;
    option.selected = name === selected;
    city.append(option);
  }
}

function chosenZone() {
  const region = $("region").value;
  return region === "UTC" ? "UTC" : `${region}/${$("city").value}`;
}

function renderZones() {
  const [region, ...rest] = settings.timezone === "UTC" ? ["UTC"] : settings.timezone.split("/");
  const select = $("region");
  select.textContent = "";
  for (const name of [...Object.keys(settings.timezones), "UTC"]) {
    const option = el("option", "", name === "UTC" ? "UTC (no time zone)" : name.replace(/_/g, " "));
    option.value = name;
    option.selected = name === region;
    select.append(option);
  }
  fillCities(region, rest.join("/"));
}

$("region").addEventListener("change", () => {
  fillCities($("region").value, "");
  $("zone-save").disabled = chosenZone() === settings.timezone;
});
$("city").addEventListener("change", () => {
  $("zone-save").disabled = chosenZone() === settings.timezone;
});
$("zone-save").addEventListener("click", () => {
  save("zone-save", "zone-note", { cmd: "set-timezone", value: chosenZone() },
    (reply) => `Saved. The clock now uses ${reply.timezone.replace(/_/g, " ")}.`);
});

// ------------------------------------------------------------ keyboard

function renderKeyboards() {
  const select = $("keyboard");
  select.textContent = "";
  for (const [code, name] of settings.keyboards) {
    const option = el("option", "", name);
    option.value = code;
    option.selected = code === settings.keyboard;
    select.append(option);
  }
}

$("keyboard").addEventListener("change", () => {
  $("keyboard-save").disabled = $("keyboard").value === settings.keyboard;
});
$("keyboard-save").addEventListener("click", async () => {
  if (await save("keyboard-save", "keyboard-note", { cmd: "set-keyboard", value: $("keyboard").value },
    () => "Saved. Try typing in the box above.")) {
    $("keyboard-test").focus();
  }
});

// ------------------------------------------------------------ password

function checkPasswords() {
  const current = $("pw-current").value;
  const fresh = $("pw-new").value;
  const again = $("pw-again").value;
  let text = "";
  if (fresh && fresh.length < 4) text = "Use at least 4 characters.";
  else if (again && fresh !== again) text = "The two new passwords are different.";
  setNote("password-note", text, text ? "error" : "");
  $("password-save").disabled = !(current && fresh.length >= 4 && fresh === again);
}

for (const id of ["pw-current", "pw-new", "pw-again"]) {
  $(id).addEventListener("input", checkPasswords);
}
$("password-save").addEventListener("click", async () => {
  const request = { cmd: "set-password", current: $("pw-current").value, new: $("pw-new").value };
  if (await save("password-save", "password-note", request, () => "Your password has been changed.")) {
    for (const id of ["pw-current", "pw-new", "pw-again"]) $(id).value = "";
    $("password-save").disabled = true;
  }
});

// ------------------------------------------------------------ browsing

$("clear-history").addEventListener("click", async () => {
  const button = $("clear-history");
  if (!button.classList.contains("danger")) {
    // Two clicks, so a slip does not wipe the history.
    button.classList.add("danger");
    button.textContent = "Clear now";
    setNote("browsing-note", "Click “Clear now” to remove your browsing history.", "warn");
    return;
  }
  button.disabled = true;
  try {
    await browser.browsingData.remove({}, { history: true, cache: true, downloads: true, formData: true });
    setNote("browsing-note", "Your browsing history has been cleared.", "good");
  } catch (err) {
    setNote("browsing-note", "Could not clear the history.", "error");
  }
  button.classList.remove("danger");
  button.textContent = "Clear";
  button.disabled = false;
});

$("open-passwords").addEventListener("click", async () => {
  const reply = await ask({ cmd: "open-passwords" });
  if (reply.ok) {
    setNote("browsing-note", "");
  } else {
    setNote("browsing-note", reply.error || "Could not open saved passwords.", "error");
  }
});

// ------------------------------------------------------------ start

async function load() {
  const reply = await ask({ cmd: "get" });
  if (!reply.ok) {
    $("load-error").textContent = reply.error || "Could not read the settings.";
    $("load-error").hidden = false;
    return;
  }
  settings = reply;
  chosen.level = levelFor(settings.tab_limit, settings.limit_is_automatic, settings.memory_mb);
  chosen.size = settings.text_size;
  $("memory").textContent = `This computer has ${(settings.memory_mb / 1024).toFixed(1)} GB of memory.`;
  renderPower();
  renderSizes();
  renderZones();
  renderKeyboards();
  for (const id of ["power-card", "text-card", "zone-card", "keyboard-card", "browsing-card"]) $(id).hidden = false;
  // On the USB stick there is no real password to change yet.
  $("password-card").hidden = Boolean(settings.live);
}

load();
