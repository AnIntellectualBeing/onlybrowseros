// Shared client for the WebOS system bridge.
//
// The bridge injects window.WEBOS_TOKEN into every HTML document it serves.
// Every /api call carries it in a custom header: a custom header cannot be set
// on a cross-origin request without a CORS preflight, and the bridge answers no
// preflights, so a hostile page in a tab cannot reach the API even though it is
// listening on a loopback port the page can address.

(function (global) {
  'use strict';

  const TOKEN = global.WEBOS_TOKEN || '';

  async function request(method, path, body) {
    const opts = {
      method,
      headers: { 'X-WebOS-Token': TOKEN },
      cache: 'no-store',
    };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }

    let res;
    try {
      res = await fetch(path, opts);
    } catch (err) {
      const e = new Error('System bridge is not responding');
      e.offline = true;
      throw e;
    }

    const text = await res.text();
    let data;
    try {
      data = text ? JSON.parse(text) : {};
    } catch (err) {
      data = { error: text.slice(0, 400) };
    }

    if (!res.ok) {
      const e = new Error(data.error || res.statusText || 'Request failed');
      e.status = res.status;
      e.data = data;
      throw e;
    }
    return data;
  }

  const api = {
    token: TOKEN,
    get: (p) => request('GET', p),
    post: (p, b) => request('POST', p, b || {}),

    status: () => request('GET', '/api/status'),
    processes: () => request('GET', '/api/processes'),
    kill: (pid, sig) => request('POST', '/api/processes/kill', { pid, signal: sig || 'TERM' }),

    wifiList: (rescan) => request('GET', '/api/wifi/list' + (rescan ? '?rescan=1' : '')),
    wifiConnect: (ssid, password) => request('POST', '/api/wifi/connect', { ssid, password }),
    wifiDisconnect: () => request('POST', '/api/wifi/disconnect', {}),

    getVolume: () => request('GET', '/api/volume'),
    setVolume: (level) => request('POST', '/api/volume/set', { level }),
    setMute: (muted) => request('POST', '/api/volume/mute', { muted }),

    getBrightness: () => request('GET', '/api/brightness'),
    setBrightness: (level) => request('POST', '/api/brightness/set', { level }),

    listFiles: (path) => request('GET', '/api/files?path=' + encodeURIComponent(path || '')),
    readFile: (path) => request('GET', '/api/files/read?path=' + encodeURIComponent(path)),
    writeFile: (path, content) => request('POST', '/api/files/write', { path, content }),
    mkdir: (path) => request('POST', '/api/files/mkdir', { path }),
    remove: (path) => request('POST', '/api/files/delete', { path }),
    rename: (path, name) => request('POST', '/api/files/rename', { path, name }),

    termOpen: (cols, rows) => request('POST', '/api/terminal/open', { cols, rows }),
    termRead: (id) => request('GET', '/api/terminal/read?id=' + encodeURIComponent(id)),
    termWrite: (id, data) => request('POST', '/api/terminal/write', { id, data }),
    termResize: (id, cols, rows) => request('POST', '/api/terminal/resize', { id, cols, rows }),
    termClose: (id) => request('POST', '/api/terminal/close', { id }),

    getConfig: () => request('GET', '/api/config'),
    setConfig: (patch) => request('POST', '/api/config', patch),

    poweroff: () => request('POST', '/api/power/shutdown', {}),
    reboot: () => request('POST', '/api/power/reboot', {}),

    disks: () => request('GET', '/api/install/disks'),
    installStart: (opts) => request('POST', '/api/install/start', opts),
    installStatus: () => request('GET', '/api/install/status'),
  };

  // Local apps run in an iframe; this is how they ask the shell to do something.
  api.shell = function (payload) {
    if (global.parent && global.parent !== global) {
      global.parent.postMessage(payload, '*');
      return true;
    }
    return false;
  };

  // Open in a new OS tab.
  api.openUrl = function (url) {
    if (!api.shell({ __webos: 'open', url })) global.location.href = url;
  };

  // Replace the current OS tab.
  api.navigate = function (url) {
    if (!api.shell({ __webos: 'navigate', url })) global.location.href = url;
  };

  // Escape text destined for innerHTML. Filenames, SSIDs and process names all
  // come from outside and several of them are attacker-influenced.
  api.esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    })[c]);
  };

  api.bytes = function (n) {
    n = Number(n) || 0;
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let i = 0;
    while (n >= 1024 && i < units.length - 1) {
      n /= 1024;
      i++;
    }
    return (i === 0 ? n : n.toFixed(1)) + ' ' + units[i];
  };

  global.WebOS = api;
})(window);
