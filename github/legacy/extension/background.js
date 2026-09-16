// WebOS Frame Bridge - service worker.
//
// Chromium is running in --kiosk --app mode, so any tab or window a page manages
// to open would appear as a bare window floating over the OS with no way to close
// it. We catch those, hand the URL to the shell so it becomes a proper OS tab,
// and dispose of the stray tab.

const SHELL_ORIGIN = 'http://127.0.0.1:9999';

async function findShellTab() {
  const tabs = await chrome.tabs.query({ url: SHELL_ORIGIN + '/*' });
  // The shell is the tab sitting at the root document, not one of its frames.
  return tabs.find((t) => !t.url.includes('/apps/')) || tabs[0] || null;
}

chrome.tabs.onCreated.addListener(async (tab) => {
  try {
    const url = tab.pendingUrl || tab.url || '';
    if (!url || url === 'about:blank') return;
    if (url.startsWith('chrome://') || url.startsWith('chrome-extension://')) return;
    if (url.startsWith(SHELL_ORIGIN)) return;

    const shell = await findShellTab();
    if (!shell || shell.id === tab.id) return;

    await chrome.tabs.sendMessage(shell.id, { __webos: 'open', url });
    await chrome.tabs.remove(tab.id);
  } catch (err) {
    // The shell may not have loaded yet, or the tab may already be gone.
    // Leaving the stray tab open is better than throwing here.
  }
});

// The shell asks for this on boot to confirm the extension is live; without it
// the shell shows a banner explaining that external sites will not embed.
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.__webos === 'ping') {
    sendResponse({ ok: true, version: chrome.runtime.getManifest().version });
    return true;
  }
  return false;
});
