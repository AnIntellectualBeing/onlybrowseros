"use strict";

// OnlyBrowserOS tab limit.
//
// The limit arrives through Firefox policy (managed storage). It is written at
// every boot by /usr/lib/onlybrowseros/tune from the machine's RAM, or from the
// number the user chose in the installer or the taskbar.

const FALLBACK_LIMIT = 2;

// Session restore reopens the previous tabs before this script can object.
// Closing tabs someone already had open would lose them, so the first seconds
// after startup are left alone; only new tabs are held to the limit.
const STARTUP_GRACE_MS = 10000;

const SETTINGS_HOST = "onlybrowseros.settings";
const SETTINGS_URL = browser.runtime.getURL("settings.html");

const startedAt = Date.now();
let limit = FALLBACK_LIMIT;
let lastNoticeAt = 0;
// The settings tab is opened by this extension and may go over the limit.
let allowNewTabUntil = 0;
const closing = new Set();

async function loadSettings() {
  let managed = {};
  try {
    managed = await browser.storage.managed.get(["maxTabs", "preferH264"]);
  } catch (err) {
    // No policy (Firefox started outside OnlyBrowserOS): keep the fallback.
  }

  const n = Number(managed.maxTabs);
  if (Number.isInteger(n) && n >= 1 && n <= 50) {
    limit = n;
  }

  if (managed.preferH264) {
    try {
      await browser.contentScripts.register({
        matches: ["<all_urls>"],
        js: [{ file: "h264.js" }],
        runAt: "document_start",
        allFrames: true,
      });
    } catch (err) {
      console.warn("tablimit: could not register the H.264 preference", err);
    }
  }
}

async function countTabs() {
  const windows = await browser.windows.getAll({
    populate: true,
    windowTypes: ["normal"],
  });
  let count = 0;
  for (const win of windows) {
    count += win.tabs.filter((t) => !closing.has(t.id)).length;
  }
  return count;
}

function notify() {
  const now = Date.now();
  if (now - lastNoticeAt < 3000) {
    return;
  }
  lastNoticeAt = now;
  const message = (limit === 1
    ? "This computer can keep 1 tab open. Close it to open another, or type a new address in it."
    : `This computer can keep ${limit} tabs open. Close one to open another.`) +
    " To change this, click the OnlyBrowserOS button next to the address bar.";
  browser.notifications.create("tab-limit", {
    type: "basic",
    title: "Tab limit reached",
    message,
  });
}

browser.tabs.onCreated.addListener(async (tab) => {
  if (Date.now() - startedAt < STARTUP_GRACE_MS) {
    return;
  }
  if (Date.now() < allowNewTabUntil) {
    allowNewTabUntil = 0;
    return;
  }
  // "Open Settings" in the taskbar and "Saved passwords" in the settings
  // arrive as ordinary new tabs.
  if (await isOwnPageTab(tab)) {
    return;
  }

  const win = await browser.windows.get(tab.windowId).catch(() => null);
  // Sign-in and payment popups are small windows of their own; they close
  // themselves and do not count.
  if (!win || win.type !== "normal") {
    return;
  }

  const count = await countTabs();
  // A tab a page opened for itself ("Sign in with Google", a checkout step)
  // gets one slot of slack, so logins still work when the limit is reached.
  const allowed = tab.openerTabId !== undefined ? limit + 1 : limit;
  if (count <= allowed) {
    return;
  }

  closing.add(tab.id);
  try {
    await browser.tabs.remove(tab.id);
  } catch (err) {
    // Already gone.
  } finally {
    closing.delete(tab.id);
  }
  notify();
});

// One browser window. The taskbar has no window list, so a second window
// (Ctrl+N, or a tab dragged out) would hide the first one with no way back.
// Its tabs are moved into the existing window instead. (Private windows are
// switched off by policy.)
browser.windows.onCreated.addListener(async (win) => {
  if (win.type !== "normal") {
    return;
  }
  const all = await browser.windows.getAll({ windowTypes: ["normal"] });
  const target = all.find((w) => w.id !== win.id && w.incognito === win.incognito);
  if (!target) {
    return;
  }

  // The new window's first tab is attached a moment after the window appears.
  await new Promise((resolve) => setTimeout(resolve, 300));

  const tabs = await browser.tabs.query({ windowId: win.id }).catch(() => []);
  if (!tabs.length) {
    return;
  }
  try {
    await browser.tabs.move(tabs.map((t) => t.id), { windowId: target.id, index: -1 });
    await browser.tabs.update(tabs[tabs.length - 1].id, { active: true });
    await browser.windows.update(target.id, { focused: true });
  } catch (err) {
    console.warn("tablimit: could not merge the new window", err);
  }
});

// ------------------------------------------------------------ settings
//
// The settings page (settings.html) asks this script, which asks the system
// through native messaging (/usr/lib/onlybrowseros/settings-host). A new
// level takes effect at once; the helper also saves it for the next start.

async function openSettings(inTabId) {
  if (inTabId !== undefined) {
    // From the start page's Settings button: open in that same tab.
    await browser.tabs.update(inTabId, { url: SETTINGS_URL });
    return;
  }
  const tabs = await browser.tabs.query({});
  const existing = tabs.find((t) => t.url === SETTINGS_URL);
  if (existing) {
    await browser.tabs.update(existing.id, { active: true });
    await browser.windows.update(existing.windowId, { focused: true });
    return;
  }
  allowNewTabUntil = Date.now() + 3000;
  await browser.tabs.create({ url: SETTINGS_URL });
}

const OWN_PAGES = [SETTINGS_URL, "about:logins"];

function isOwnPage(url) {
  return OWN_PAGES.some((page) => String(url || "").startsWith(page));
}

async function isOwnPageTab(tab) {
  if (isOwnPage(tab.url)) {
    return true;
  }
  // A tab opened with an address starts out blank for a moment.
  await new Promise((resolve) => setTimeout(resolve, 400));
  const current = await browser.tabs.get(tab.id).catch(() => null);
  return Boolean(current && isOwnPage(current.url));
}

async function askSystem(message) {
  try {
    const reply = await browser.runtime.sendNativeMessage(SETTINGS_HOST, message);
    return reply || { ok: false, error: "No answer from the system." };
  } catch (err) {
    return { ok: false, error: "Settings can only be changed on a computer running OnlyBrowserOS." };
  }
}

browser.browserAction.onClicked.addListener(() => {
  openSettings().catch((err) => console.warn("tablimit: could not open settings", err));
});

browser.runtime.onMessage.addListener((message, sender) => {
  const type = message && message.type;
  if (type === "open-settings" && sender.tab) {
    return openSettings(sender.tab.id);
  }
  // Reading and changing settings is for the extension's own page only.
  const fromSettingsPage = typeof sender.url === "string" && sender.url.startsWith(SETTINGS_URL);
  if (type === "system" && fromSettingsPage && message.request) {
    return askSystem(message.request).then((reply) => {
      const n = Number(reply.tab_limit);
      if (message.request.cmd === "set-tabs" && reply.ok && Number.isInteger(n) && n >= 1 && n <= 50) {
        limit = n;
      }
      return reply;
    });
  }
  // The Downloads page lists files and deletes downloaded ones, nothing else.
  const fromFilesPage = typeof sender.url === "string" && sender.url.startsWith(FILES_PAGE);
  if (type === "list-files" && fromFilesPage) {
    return askSystem({ cmd: "list-files" });
  }
  if (type === "delete-file" && fromFilesPage) {
    return askSystem({ cmd: "delete-file", path: String(message.path || "") });
  }
  return undefined;
});

// ------------------------------------------------------------ downloads
//
// This computer keeps only files the browser itself can open: PDFs, pictures,
// videos, music and plain text. Anything else (installers, archives, office
// documents) is stopped as it starts, because nothing here could open it.
// Keep in step with OPENABLE in /usr/lib/onlybrowseros/settings-host.

const OPENABLE_EXTENSIONS = new Set([
  "pdf",
  "jpg", "jpeg", "png", "gif", "webp", "avif", "bmp", "svg",
  "mp4", "webm", "ogv",
  "mp3", "ogg", "oga", "opus", "wav", "m4a", "flac",
  "txt",
]);
const OPENABLE_TYPES = new RegExp(
  "^(application/pdf|image/(jpeg|png|gif|webp|avif|bmp|svg\\+xml)|video/(mp4|webm|ogg)|" +
  "audio/(mpeg|mp3|mp4|x-m4a|ogg|opus|wav|x-wav|wave|flac|x-flac)|text/plain)$", "i");
const FILES_PAGE = "file:///usr/share/onlybrowseros/start/downloads.html";
const screened = new Set();

function fileExtension(path) {
  const name = String(path || "").split(/[\\/]/).pop().split(/[?#]/)[0];
  const match = /\.([A-Za-z0-9]{1,5})$/.exec(name);
  return match ? match[1].toLowerCase() : "";
}

function browserCanOpen(item) {
  const extension = fileExtension(item.filename);
  if (extension) {
    return OPENABLE_EXTENSIONS.has(extension);
  }
  return OPENABLE_TYPES.test(item.mime || "");
}

async function screenDownload(item) {
  // The file name or type may only be known a moment after the download starts.
  if (screened.has(item.id) || !(item.filename || item.mime)) {
    return;
  }
  screened.add(item.id);
  if (browserCanOpen(item)) {
    return;
  }
  await browser.downloads.cancel(item.id).catch(() => {});
  const [now] = await browser.downloads.search({ id: item.id }).catch(() => []);
  if (now && now.exists && now.state === "complete") {
    await browser.downloads.removeFile(item.id).catch(() => {});
  }
  await browser.downloads.erase({ id: item.id }).catch(() => {});
  const name = String(item.filename || "").split(/[\\/]/).pop() || "The file";
  browser.notifications.create(`download-stopped-${item.id}`, {
    type: "basic",
    title: "Download stopped",
    message: `“${name}” was not saved. This computer keeps only files the browser can open: ` +
      "PDFs, pictures, videos, music and text.",
  });
}

browser.downloads.onCreated.addListener((item) => {
  screenDownload(item);
});

browser.downloads.onChanged.addListener(async (delta) => {
  if (!delta.filename && !delta.mime) {
    return;
  }
  const [item] = await browser.downloads.search({ id: delta.id }).catch(() => []);
  if (item) {
    screenDownload(item);
  }
});

loadSettings();
