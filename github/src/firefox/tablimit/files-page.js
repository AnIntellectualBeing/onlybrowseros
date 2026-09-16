"use strict";

// Runs on the OnlyBrowserOS Downloads page (start/downloads.html). Lists the
// downloaded files, and the files on plugged-in USB sticks, that the browser
// can open. The lists come from /usr/lib/onlybrowseros/settings-host through
// the background script. Clicking a file opens it in this tab.

const KINDS = {
  pdf: { name: "PDF", icon: '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/><path d="M10 13h6M10 17h6"/>' },
  picture: { name: "Picture", icon: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m3 16 5-5 4 4 3-3 6 6"/><circle cx="15.5" cy="9" r="1.5"/>' },
  video: { name: "Video", icon: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="m10 9 5 3-5 3z"/>' },
  music: { name: "Music", icon: '<path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/>' },
  text: { name: "Text", icon: '<path d="M6 3h12v18H6z"/><path d="M9 8h6M9 12h6M9 16h3"/>' },
};

const $ = (id) => document.getElementById(id);
let lastData = "";

function kindIcon(kind) {
  const span = document.createElement("span");
  span.className = "thumb";
  span.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" ' +
    `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${(KINDS[kind] || KINDS.text).icon}</svg>`;
  return span;
}

function sizeText(bytes) {
  if (bytes < 1024) return `${bytes} bytes`;
  if (bytes < 1048576) return `${Math.round(bytes / 1024)} KB`;
  if (bytes < 1073741824) return `${(bytes / 1048576).toFixed(1)} MB`;
  return `${(bytes / 1073741824).toFixed(1)} GB`;
}

function dateText(seconds) {
  const date = new Date(seconds * 1000);
  const now = new Date();
  if (date.toDateString() === now.toDateString()) {
    return `Today, ${date.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}`;
  }
  return date.toLocaleDateString(undefined, {
    day: "numeric", month: "short", year: date.getFullYear() === now.getFullYear() ? undefined : "numeric",
  });
}

// Downloads get picture previews and a Delete button. USB sticks get plain
// icons: decoding hundreds of camera photos would not fit in 1 GB of memory.
function fileRow(file, isDownload) {
  const row = document.createElement("li");
  row.className = "file";
  const link = document.createElement("a");
  link.className = "open";
  link.href = file.url;

  let thumb = kindIcon(file.kind);
  if (isDownload && file.kind === "picture") {
    thumb = document.createElement("span");
    thumb.className = "thumb";
    const img = document.createElement("img");
    img.src = file.url;
    img.alt = "";
    img.loading = "lazy";
    img.addEventListener("error", () => thumb.replaceWith(kindIcon("picture")));
    thumb.append(img);
  }

  const words = document.createElement("span");
  words.className = "words";
  const name = document.createElement("strong");
  name.textContent = file.name;
  const detail = document.createElement("span");
  detail.textContent = [
    (KINDS[file.kind] || KINDS.text).name,
    sizeText(file.size),
    file.folder ? `in ${file.folder}` : dateText(file.modified),
  ].join(" · ");
  words.append(name, detail);
  link.append(thumb, words);
  row.append(link);

  if (isDownload) {
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "delete";
    remove.textContent = "Delete";
    remove.addEventListener("click", async () => {
      if (!remove.classList.contains("confirm")) {
        // Two clicks, so a slip does not lose a file.
        remove.classList.add("confirm");
        remove.textContent = "Delete for good";
        setTimeout(() => {
          remove.classList.remove("confirm");
          remove.textContent = "Delete";
        }, 4000);
        return;
      }
      remove.disabled = true;
      const reply = await browser.runtime.sendMessage({ type: "delete-file", path: file.path }).catch(() => null);
      if (!reply || !reply.ok) {
        $("note").textContent = (reply && reply.error) || "Could not delete the file.";
      }
      load(true);
    });
    row.append(remove);
  }
  return row;
}

async function load(force) {
  const reply = await browser.runtime.sendMessage({ type: "list-files" }).catch(() => null);
  document.body.dataset.ready = "1";
  $("loading").hidden = true;
  if (!reply || !reply.ok) {
    $("note").textContent = (reply && reply.error) || "Could not read your files.";
    return;
  }
  const data = JSON.stringify([reply.downloads, reply.usb]);
  if (data === lastData && !force) {
    return;
  }
  lastData = data;
  $("note").textContent = "";

  const list = $("downloads");
  list.textContent = "";
  for (const file of reply.downloads) {
    list.append(fileRow(file, true));
  }
  $("downloads-empty").hidden = reply.downloads.length > 0;

  const usb = $("usb");
  usb.textContent = "";
  for (const stick of reply.usb) {
    const title = document.createElement("h2");
    title.textContent = `USB stick: ${stick.name}`;
    usb.append(title);
    if (!stick.files.length) {
      const empty = document.createElement("p");
      empty.className = "empty";
      empty.textContent = "No PDFs, pictures, videos, music or text on this USB stick.";
      usb.append(empty);
      continue;
    }
    const files = document.createElement("ul");
    files.className = "files";
    for (const file of stick.files) {
      files.append(fileRow(file, false));
    }
    usb.append(files);
  }
}

load(true);
// New downloads and USB sticks plugged in appear by themselves.
setInterval(() => {
  if (document.visibilityState === "visible") {
    load(false);
  }
}, 5000);
