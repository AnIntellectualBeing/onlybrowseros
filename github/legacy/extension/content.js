// WebOS Frame Bridge - content script, injected into every frame.
//
// Runs in an isolated world, so it talks to the shell with window.postMessage
// rather than touching page globals.

(function () {
  'use strict';

  const SHELL_ORIGIN = 'http://127.0.0.1:9999';
  const isTop = window === window.top;
  const isShell = location.origin === SHELL_ORIGIN;

  function toTop(payload) {
    try {
      window.top.postMessage(payload, '*');
    } catch (err) {
      /* cross-origin top is still reachable via postMessage; ignore failures */
    }
  }

  // --- Shell side: relay messages from the service worker into the page ------
  if (isShell && isTop) {
    chrome.runtime.onMessage.addListener((msg) => {
      if (msg && msg.__webos) window.postMessage(msg, SHELL_ORIGIN);
    });
    // Announce that header stripping is active.
    window.postMessage({ __webos: 'bridge-ready' }, SHELL_ORIGIN);
    return;
  }

  // --- Frame side -----------------------------------------------------------
  if (isTop) return; // A top-level page that is not the shell: nothing to relay.

  function favicon() {
    const rels = ['icon', 'shortcut icon', 'apple-touch-icon'];
    for (const rel of rels) {
      const link = document.querySelector(`link[rel="${rel}" i]`);
      if (link && link.href) return link.href;
    }
    return location.origin + '/favicon.ico';
  }

  let lastTitle = null;
  let lastUrl = null;

  function reportMeta() {
    const title = document.title || location.hostname;
    if (title === lastTitle && location.href === lastUrl) return;
    lastTitle = title;
    lastUrl = location.href;
    toTop({ __webos: 'meta', title, url: location.href, favicon: favicon() });
  }

  document.addEventListener('DOMContentLoaded', reportMeta);
  window.addEventListener('load', reportMeta);
  setInterval(reportMeta, 1000); // catches SPA route changes and late <title> writes

  // Frames cannot navigate the shell, so links that would break out become
  // requests for a new OS tab instead of silently doing nothing.
  document.addEventListener(
    'click',
    (e) => {
      const a = e.target && e.target.closest && e.target.closest('a[href]');
      if (!a) return;
      const target = (a.getAttribute('target') || '').toLowerCase();
      if (target !== '_blank' && target !== '_top' && target !== '_parent') return;
      const href = a.href;
      if (!href || href.startsWith('javascript:')) return;
      e.preventDefault();
      e.stopPropagation();
      toTop({ __webos: 'open', url: href });
    },
    true
  );

  // Keyboard shortcuts have to work while focus is inside a site, so forward
  // the browser-level combinations up to the shell.
  document.addEventListener(
    'keydown',
    (e) => {
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
      }
      if (!action) return;
      e.preventDefault();
      e.stopPropagation();
      toTop({ __webos: 'shortcut', action });
    },
    true
  );
})();
