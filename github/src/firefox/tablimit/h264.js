"use strict";

// Registered only on low-memory machines (preferH264 in the policy).
//
// Laptops of that age decode H.264 in hardware, or at least cheaply in
// software; VP9 and AV1 make YouTube stutter and drain the battery on them.
// Telling pages those two codecs are unsupported makes sites that offer a
// choice fall back to H.264.

(() => {
  const page = window.wrappedJSObject;
  if (!page) {
    return;
  }
  const blocked = /vp0?9|av01/i;

  if (page.MediaSource && page.MediaSource.isTypeSupported) {
    const original = page.MediaSource.isTypeSupported;
    exportFunction(
      function isTypeSupported(type) {
        if (blocked.test(String(type))) {
          return false;
        }
        return original.call(page.MediaSource, type);
      },
      page.MediaSource,
      { defineAs: "isTypeSupported" }
    );
  }

  const proto = page.HTMLMediaElement && page.HTMLMediaElement.prototype;
  if (proto && proto.canPlayType) {
    const originalCanPlay = proto.canPlayType;
    exportFunction(
      function canPlayType(type) {
        if (blocked.test(String(type))) {
          return "";
        }
        return originalCanPlay.call(this, type);
      },
      proto,
      { defineAs: "canPlayType" }
    );
  }
})();
