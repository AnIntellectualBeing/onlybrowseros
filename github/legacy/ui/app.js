// WebOS shell: system tray, tab engine and the message bus that local apps,
// embedded sites and the Chromium extension all speak to.
'use strict';

const HOME = '/newtab.html';

const APP_TITLES = {
  '/newtab.html': 'Dashboard',
  '/apps/task_manager.html': 'System Monitor',
  '/apps/web_terminal.html': 'Terminal',
  '/apps/file_explorer.html': 'Files',
  '/apps/text_editor.html': 'Text Editor',
  '/apps/settings.html': 'Settings',
  '/apps/installer.html': 'Install WebOS',
};

const APP_GLYPHS = {
  '/newtab.html': '🏠',
  '/apps/task_manager.html': '📊',
  '/apps/web_terminal.html': '💻',
  '/apps/file_explorer.html': '📁',
  '/apps/text_editor.html': '📝',
  '/apps/settings.html': '⚙️',
  '/apps/installer.html': '💾',
};

const $ = (id) => document.getElementById(id);

const tabsContainer = $('tabs-container');
const viewportContainer = $('viewport-container');
const addressInput = $('address-input');
const lockIcon = $('lock-icon');

let tabs = [];
let activeTabId = null;
let tabSeq = 0;
let settings = { searchEngine: 'https://duckduckgo.com/?q=' };

/* ------------------------------------------------------------------ toasts */

function toast(message, kind, ms) {
  const el = document.createElement('div');
  el.className = 'toast' + (kind ? ' ' + kind : '');
  el.textContent = message;
  $('toast-stack').appendChild(el);
  setTimeout(() => el.remove(), ms || 4000);
}

/* ------------------------------------------------------------------ modals */

let modalResolve = null;

function modal({ title, body, input, password, okLabel }) {
  return new Promise((resolve) => {
    modalResolve = resolve;
    $('modal-title').textContent = title || '';
    $('modal-body').textContent = body || '';
    const field = $('modal-input');
    field.style.display = input ? 'block' : 'none';
    field.type = password ? 'password' : 'text';
    field.value = '';
    $('modal-ok').textContent = okLabel || 'OK';
    $('modal-backdrop').classList.add('active');
    if (input) setTimeout(() => field.focus(), 50);
    else setTimeout(() => $('modal-ok').focus(), 50);
  });
}

function closeModal(value) {
  $('modal-backdrop').classList.remove('active');
  const resolve = modalResolve;
  modalResolve = null;
  if (resolve) resolve(value);
}

$('modal-ok').addEventListener('click', () => {
  const field = $('modal-input');
  closeModal(field.style.display === 'none' ? true : field.value);
});
$('modal-cancel').addEventListener('click', () => closeModal(null));
$('modal-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') $('modal-ok').click();
  if (e.key === 'Escape') closeModal(null);
});

const confirmBox = (title, body, okLabel) =>
  modal({ title, body, okLabel }).then((v) => v === true);

/* ----------------------------------------------------------------- drawers */

const DRAWERS = ['apps-drawer', 'wifi-drawer', 'volume-drawer', 'power-drawer'];

function closeDrawers() {
  DRAWERS.forEach((id) => $(id).classList.remove('active'));
  document.querySelectorAll('.tray-item').forEach((el) => el.classList.remove('active'));
}

function toggleDrawer(drawerId, trayId, onOpen) {
  const drawer = $(drawerId);
  const wasOpen = drawer.classList.contains('active');
  closeDrawers();
  if (wasOpen) return;
  drawer.classList.add('active');
  if (trayId) $(trayId).classList.add('active');
  if (onOpen) onOpen();
}

document.querySelectorAll('[data-close]').forEach((el) =>
  el.addEventListener('click', closeDrawers)
);

document.addEventListener('click', (e) => {
  if (!e.target.closest('.drawer-overlay') && !e.target.closest('.tray-item')) closeDrawers();
});

// Clicking into an iframe does not fire a click on the shell document, so
// drawers would stay open over the page. Blur is the reliable signal.
window.addEventListener('blur', () => setTimeout(closeDrawers, 120));

/* ------------------------------------------------------------- URL helpers */

function isLocal(url) {
  return url.startsWith('/');
}

function displayUrl(url) {
  if (url === HOME) return 'webos://home';
  const m = url.match(/^\/apps\/([\w-]+)\.html$/);
  if (m) return 'webos://' + m[1].replace(/_/g, '-');
  return url;
}

function resolveInput(raw) {
  let s = String(raw || '').trim();
  if (!s) return HOME;

  if (s === 'webos://home' || s === 'webos://') return HOME;
  const m = s.match(/^webos:\/\/([\w-]+)$/);
  if (m) {
    const candidate = '/apps/' + m[1].replace(/-/g, '_') + '.html';
    return APP_TITLES[candidate] ? candidate : HOME;
  }

  if (s.startsWith('/') || /^https?:\/\//i.test(s)) return s;
  if (/^file:\/\//i.test(s)) return s;

  // A bare token with a dot and no spaces is a hostname; anything else is a query.
  if (/^[^\s]+\.[^\s]{2,}$/.test(s) && !s.includes(' ')) return 'https://' + s;
  return settings.searchEngine + encodeURIComponent(s);
}

function shortTitle(url) {
  if (APP_TITLES[url]) return APP_TITLES[url];
  try {
    return new URL(url, location.origin).hostname || url;
  } catch (err) {
    return url;
  }
}

/* -------------------------------------------------------------- tab engine */

function getTab(id) {
  return tabs.find((t) => t.id === id) || null;
}

function activeTab() {
  return getTab(activeTabId);
}

function tabForWindow(win) {
  return tabs.find((t) => t.frame && t.frame.contentWindow === win) || null;
}

const EXTERNAL_SANDBOX = [
  'allow-scripts',
  'allow-same-origin',
  'allow-forms',
  'allow-modals',
  'allow-popups',
  'allow-popups-to-escape-sandbox',
  'allow-downloads',
  'allow-pointer-lock',
  'allow-presentation',
  'allow-orientation-lock',
  'allow-storage-access-by-user-activation',
].join(' ');
// allow-top-navigation is deliberately absent: without it a page that tries to
// bust out of the frame cannot replace the whole OS with itself.

function createTab(url, { background } = {}) {
  const target = url || HOME;
  const tab = {
    id: 'tab' + ++tabSeq,
    url: target,
    title: shortTitle(target),
    favicon: null,
    loading: true,
    history: [target],
    histIndex: 0,
    frame: null,
  };

  const frame = document.createElement('iframe');
  frame.className = 'tab-viewport';
  frame.setAttribute('allow', 'autoplay; fullscreen; clipboard-read; clipboard-write; encrypted-media');
  if (!isLocal(target)) frame.setAttribute('sandbox', EXTERNAL_SANDBOX);
  frame.addEventListener('load', () => {
    tab.loading = false;
    renderTabs();
  });
  frame.src = target;
  tab.frame = frame;
  viewportContainer.appendChild(frame);

  tabs.push(tab);
  if (!background) switchTab(tab.id);
  else renderTabs();
  return tab;
}

function switchTab(id) {
  const tab = getTab(id);
  if (!tab) return;
  activeTabId = id;
  tabs.forEach((t) => t.frame.classList.toggle('active', t.id === id));
  syncChrome();
  renderTabs();
  try {
    tab.frame.contentWindow.focus();
  } catch (err) {
    /* cross-origin frames refuse focus() */
  }
}

function closeTab(id, event) {
  if (event) event.stopPropagation();
  const idx = tabs.findIndex((t) => t.id === id);
  if (idx === -1) return;

  if (tabs.length === 1) {
    navigate(id, HOME);
    return;
  }

  tabs[idx].frame.remove();
  tabs.splice(idx, 1);

  if (activeTabId === id) switchTab(tabs[Math.max(0, idx - 1)].id);
  else renderTabs();
}

function applySandbox(tab, url) {
  // Frames swap between local apps and the open web, so the sandbox has to be
  // re-evaluated on every navigation, not just at creation.
  if (isLocal(url)) tab.frame.removeAttribute('sandbox');
  else tab.frame.setAttribute('sandbox', EXTERNAL_SANDBOX);
}

function navigate(id, rawUrl, { push = true } = {}) {
  const tab = getTab(id);
  if (!tab) return;
  const url = isLocal(rawUrl) || /^https?:|^file:/i.test(rawUrl) ? rawUrl : resolveInput(rawUrl);

  tab.url = url;
  tab.title = shortTitle(url);
  tab.favicon = null;
  tab.loading = true;

  if (push) {
    tab.history = tab.history.slice(0, tab.histIndex + 1);
    tab.history.push(url);
    tab.histIndex = tab.history.length - 1;
  }

  applySandbox(tab, url);
  tab.frame.src = url;

  if (id === activeTabId) syncChrome();
  renderTabs();
}

function goBack(id) {
  const tab = getTab(id);
  if (!tab || tab.histIndex <= 0) return;
  tab.histIndex--;
  navigate(id, tab.history[tab.histIndex], { push: false });
}

function goForward(id) {
  const tab = getTab(id);
  if (!tab || tab.histIndex >= tab.history.length - 1) return;
  tab.histIndex++;
  navigate(id, tab.history[tab.histIndex], { push: false });
}

function reload(id) {
  const tab = getTab(id);
  if (!tab) return;
  tab.loading = true;
  renderTabs();
  // Reassigning .src re-fetches even when the URL is unchanged.
  const url = tab.url;
  tab.frame.src = 'about:blank';
  setTimeout(() => {
    tab.frame.src = url;
  }, 20);
}

function renderTabs() {
  tabsContainer.textContent = '';
  tabs.forEach((tab) => {
    const el = document.createElement('div');
    el.className = 'tab' + (tab.id === activeTabId ? ' active' : '');
    el.title = tab.title;

    if (tab.loading) {
      const spin = document.createElement('div');
      spin.className = 'tab-spinner';
      el.appendChild(spin);
    } else if (tab.favicon) {
      const img = document.createElement('img');
      img.className = 'tab-favicon';
      img.src = tab.favicon;
      img.addEventListener('error', () => {
        tab.favicon = null;
        img.replaceWith(glyphFor(tab));
      });
      el.appendChild(img);
    } else {
      el.appendChild(glyphFor(tab));
    }

    const title = document.createElement('span');
    title.className = 'tab-title';
    title.textContent = tab.title;
    el.appendChild(title);

    const close = document.createElement('span');
    close.className = 'tab-close';
    close.textContent = '✕';
    close.addEventListener('click', (e) => closeTab(tab.id, e));
    el.appendChild(close);

    el.addEventListener('click', () => switchTab(tab.id));
    el.addEventListener('auxclick', (e) => {
      if (e.button === 1) closeTab(tab.id, e);
    });
    tabsContainer.appendChild(el);
  });
}

function glyphFor(tab) {
  const span = document.createElement('span');
  span.className = 'tab-glyph';
  span.textContent = APP_GLYPHS[tab.url] || '🌐';
  return span;
}

function syncChrome() {
  const tab = activeTab();
  if (!tab) return;
  if (document.activeElement !== addressInput) addressInput.value = displayUrl(tab.url);

  if (isLocal(tab.url)) {
    lockIcon.textContent = '🌐';
    lockIcon.className = 'lock-icon';
  } else if (/^https:/i.test(tab.url)) {
    lockIcon.textContent = '🔒';
    lockIcon.className = 'lock-icon';
  } else {
    lockIcon.textContent = '⚠';
    lockIcon.className = 'lock-icon insecure';
  }

  $('btn-back').disabled = tab.histIndex <= 0;
  $('btn-forward').disabled = tab.histIndex >= tab.history.length - 1;
}

/* -------------------------------------------------------------- message bus */

window.addEventListener('message', (e) => {
  const d = e.data;
  if (!d || typeof d !== 'object' || !d.__webos) return;

  const source = tabForWindow(e.source);

  switch (d.__webos) {
    case 'meta': {
      if (!source) break;
      if (typeof d.title === 'string' && d.title.trim()) source.title = d.title.trim().slice(0, 120);
      if (typeof d.favicon === 'string') source.favicon = d.favicon;
      // Track in-page navigation so the address bar follows SPA route changes.
      if (typeof d.url === 'string' && d.url !== source.url && !isLocal(source.url)) {
        source.url = d.url;
        source.history[source.histIndex] = d.url;
        if (source.id === activeTabId) syncChrome();
      }
      renderTabs();
      break;
    }

    case 'open':
      if (d.url) createTab(d.url);
      break;

    case 'navigate':
      if (d.url) navigate(source ? source.id : activeTabId, d.url);
      break;

    case 'shortcut':
      runShortcut(d.action);
      break;

    case 'bridge-ready':
      window.__webosBridgeReady = true;
      break;

    default:
      break;
  }
});

function runShortcut(action) {
  const id = activeTabId;
  switch (action) {
    case 'new-tab': createTab(HOME); break;
    case 'close-tab': closeTab(id); break;
    case 'reload': reload(id); break;
    case 'back': goBack(id); break;
    case 'forward': goForward(id); break;
    case 'focus-address': addressInput.focus(); addressInput.select(); break;
    default: break;
  }
}

document.addEventListener('keydown', (e) => {
  let action = null;
  if (e.ctrlKey && !e.shiftKey && !e.altKey) {
    if (e.key === 't') action = 'new-tab';
    else if (e.key === 'w') action = 'close-tab';
    else if (e.key === 'l') action = 'focus-address';
    else if (e.key === 'r') action = 'reload';
  } else if (e.altKey && !e.ctrlKey) {
    if (e.key === 'ArrowLeft') action = 'back';
    else if (e.key === 'ArrowRight') action = 'forward';
  } else if (e.key === 'F5') {
    action = 'reload';
  } else if (e.key === 'Escape') {
    closeDrawers();
  }
  if (!action) return;
  e.preventDefault();
  runShortcut(action);
});

/* ----------------------------------------------------------- chrome wiring */

$('btn-new-tab').addEventListener('click', () => createTab(HOME));
$('btn-home').addEventListener('click', () => navigate(activeTabId, HOME));
$('btn-reload').addEventListener('click', () => reload(activeTabId));
$('btn-back').addEventListener('click', () => goBack(activeTabId));
$('btn-forward').addEventListener('click', () => goForward(activeTabId));

addressInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    navigate(activeTabId, resolveInput(addressInput.value));
    addressInput.blur();
  } else if (e.key === 'Escape') {
    syncChrome();
    addressInput.blur();
  }
});
addressInput.addEventListener('focus', () => addressInput.select());
addressInput.addEventListener('blur', () => syncChrome());

document.querySelectorAll('.app-launch').forEach((el) =>
  el.addEventListener('click', () => {
    closeDrawers();
    const url = el.dataset.app;
    const existing = tabs.find((t) => t.url === url);
    if (existing) switchTab(existing.id);
    else createTab(url);
  })
);

/* --------------------------------------------------------------- tray: apps */

$('tray-apps').addEventListener('click', () => toggleDrawer('apps-drawer', 'tray-apps'));

/* --------------------------------------------------------------- tray: wifi */

$('tray-wifi').addEventListener('click', () =>
  toggleDrawer('wifi-drawer', 'tray-wifi', () => loadWifi(true))
);
$('btn-rescan-wifi').addEventListener('click', () => loadWifi(true));
$('btn-disconnect-wifi').addEventListener('click', async () => {
  try {
    await WebOS.wifiDisconnect();
    toast('Disconnected from Wi-Fi', 'success');
    loadWifi(false);
  } catch (err) {
    toast(err.message, 'error');
  }
});

async function loadWifi(rescan) {
  const list = $('wifi-network-list');
  list.textContent = '';
  const loading = document.createElement('div');
  loading.className = 'wifi-item';
  loading.textContent = rescan ? 'Scanning…' : 'Loading…';
  list.appendChild(loading);

  let data;
  try {
    data = await WebOS.wifiList(rescan);
  } catch (err) {
    list.textContent = '';
    const row = document.createElement('div');
    row.className = 'wifi-item';
    row.textContent = err.offline ? 'System bridge offline' : err.message;
    list.appendChild(row);
    return;
  }

  $('wifi-current').textContent = data.available
    ? data.device || ''
    : '';

  list.textContent = '';
  if (!data.networks || !data.networks.length) {
    const row = document.createElement('div');
    row.className = 'wifi-item';
    row.textContent = data.available === false
      ? 'No Wi-Fi adapter detected'
      : 'No networks found';
    list.appendChild(row);
    return;
  }

  data.networks.forEach((net) => {
    const row = document.createElement('div');
    row.className = 'wifi-item' + (net.active ? ' connected' : '');

    const left = document.createElement('div');
    const name = document.createElement('strong');
    name.textContent = net.ssid;
    const meta = document.createElement('div');
    meta.className = 'wifi-meta';
    meta.textContent = (net.security || 'Open') + (net.saved ? ' · saved' : '');
    left.appendChild(name);
    left.appendChild(meta);

    const right = document.createElement('span');
    right.textContent = net.active ? 'Connected' : net.signal + '%';

    row.appendChild(left);
    row.appendChild(right);
    row.addEventListener('click', () => connectWifi(net));
    list.appendChild(row);
  });
}

async function connectWifi(net) {
  if (net.active) return;

  let password = '';
  const secured = net.security && net.security !== 'Open' && net.security !== '--';
  if (secured && !net.saved) {
    password = await modal({
      title: 'Connect to ' + net.ssid,
      body: net.security + ' network. Enter the Wi-Fi password.',
      input: true,
      password: true,
      okLabel: 'Connect',
    });
    if (password === null) return;
  }

  toast('Connecting to ' + net.ssid + '…');
  try {
    const res = await WebOS.wifiConnect(net.ssid, password);
    toast(res.message || 'Connected', res.success ? 'success' : 'error');
  } catch (err) {
    toast(err.message, 'error');
  }
  loadWifi(false);
  refreshTray();
}

/* ------------------------------------------------------- tray: audio/display */

$('tray-volume').addEventListener('click', () =>
  toggleDrawer('volume-drawer', 'tray-volume', loadAudioDisplay)
);

async function loadAudioDisplay() {
  try {
    const v = await WebOS.getVolume();
    $('slider-volume').value = v.level;
    $('volume-val').textContent = v.muted ? 'Muted' : v.level + '%';
  } catch (err) { /* tray keeps last known value */ }

  try {
    const b = await WebOS.getBrightness();
    if (b.available) {
      $('slider-brightness').disabled = false;
      $('slider-brightness').value = b.level;
      $('brightness-val').textContent = b.level + '%';
      $('brightness-note').textContent = '';
    } else {
      $('slider-brightness').disabled = true;
      $('brightness-val').textContent = 'n/a';
      $('brightness-note').textContent = 'No backlight control on this display.';
    }
  } catch (err) { /* leave disabled */ }
}

let volumeTimer = null;
$('slider-volume').addEventListener('input', (e) => {
  const val = parseInt(e.target.value, 10);
  $('volume-val').textContent = val + '%';
  $('volume-status-text').textContent = val + '%';
  $('volume-icon').textContent = val === 0 ? '🔇' : val < 50 ? '🔉' : '🔊';
  clearTimeout(volumeTimer);
  volumeTimer = setTimeout(() => WebOS.setVolume(val).catch(() => {}), 60);
});

let brightnessTimer = null;
$('slider-brightness').addEventListener('input', (e) => {
  const val = parseInt(e.target.value, 10);
  $('brightness-val').textContent = val + '%';
  clearTimeout(brightnessTimer);
  brightnessTimer = setTimeout(() => WebOS.setBrightness(val).catch(() => {}), 60);
});

/* -------------------------------------------------------------- tray: power */

$('tray-power').addEventListener('click', () => toggleDrawer('power-drawer', 'tray-power'));

$('btn-power-shutdown').addEventListener('click', async () => {
  if (!(await confirmBox('Shut down', 'Shut down WebOS now?', 'Shut Down'))) return;
  WebOS.poweroff().catch((err) => toast(err.message, 'error'));
});

$('btn-power-reboot').addEventListener('click', async () => {
  if (!(await confirmBox('Restart', 'Restart WebOS now?', 'Restart'))) return;
  WebOS.reboot().catch((err) => toast(err.message, 'error'));
});

/* ---------------------------------------------------------------- tray poll */

function startClock() {
  const tick = () => {
    $('system-time').textContent = new Date().toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
    });
  };
  tick();
  setInterval(tick, 10000);
}

async function refreshTray() {
  let s;
  try {
    s = await WebOS.status();
  } catch (err) {
    $('wifi-status-text').textContent = 'Offline';
    return;
  }

  if (s.battery && s.battery.present) {
    const charging = /charg|full/i.test(s.battery.status);
    $('battery-icon').textContent = charging ? '🔌' : s.battery.percent < 20 ? '🪫' : '🔋';
    $('battery-status-text').textContent = s.battery.percent + '%';
  } else {
    $('battery-icon').textContent = '🔌';
    $('battery-status-text').textContent = 'AC';
  }

  if (s.network) {
    $('wifi-status-text').textContent = s.network.ssid || (s.network.connected ? 'Wired' : 'No network');
    $('wifi-icon').textContent = s.network.connected ? (s.network.ssid ? '📶' : '🔌') : '📵';
  }

  if (s.volume) {
    $('volume-status-text').textContent = s.volume.muted ? 'Muted' : s.volume.level + '%';
    $('volume-icon').textContent = s.volume.muted || s.volume.level === 0 ? '🔇'
      : s.volume.level < 50 ? '🔉' : '🔊';
  }

  $('power-session').textContent =
    (s.live ? 'Live session' : 'Installed system') +
    ' · up ' + (s.uptime || '—') +
    ' · ' + (s.hostname || '');
}

/* ------------------------------------------------------------------- boot */

async function boot() {
  try {
    const cfg = await WebOS.getConfig();
    if (cfg.searchEngine) settings.searchEngine = cfg.searchEngine;
  } catch (err) { /* defaults are fine */ }

  startClock();
  refreshTray();
  setInterval(refreshTray, 5000);

  createTab(HOME);

  // If the header-stripping extension did not load, external sites will render
  // as blank frames and the cause is not obvious. Say so once.
  setTimeout(() => {
    if (!window.__webosBridgeReady) {
      toast('Frame Bridge extension not loaded — some sites may refuse to embed.', 'error', 9000);
    }
  }, 4000);
}

boot();
