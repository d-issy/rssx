(function () {
  "use strict";

  const READ_DELAY_MS = 2000;
  let selectedIndex = -1;
  let autoReadTimer = null;

  function entries() {
    return Array.from(document.querySelectorAll("#entries .entry"));
  }

  function isTyping() {
    const el = document.activeElement;
    if (!el) return false;
    const tag = el.tagName;
    return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
  }

  function collapse(entryEl) {
    const body = entryEl.querySelector(".entry-body");
    if (!body || body.hidden) return;
    body.hidden = true;
    entryEl.classList.remove("expanded");
  }

  function select(index, opts = {}) {
    const list = entries();
    if (list.length === 0) return;
    index = Math.max(0, Math.min(list.length - 1, index));
    list.forEach((el, i) => el.classList.toggle("selected", i === index));
    selectedIndex = index;
    const el = list[index];
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    if (opts.expand) {
      clearAutoRead();
      list.forEach((other, i) => {
        if (i !== index) collapse(other);
      });
      if (!el.classList.contains("expanded")) {
        toggleExpand(el);
      }
    }
  }

  function clearAutoRead() {
    if (autoReadTimer) {
      clearTimeout(autoReadTimer);
      autoReadTimer = null;
    }
  }

  function markRead(entryEl, value) {
    const id = entryEl.dataset.entryId;
    fetch(`/entries/${id}/read?value=${value ? 1 : 0}`, { method: "POST" })
      .then((r) => r.text())
      .then((html) => {
        replaceEntry(entryEl, html);
        notifyCountsChanged();
      });
  }

  function notifyCountsChanged() {
    document.body.dispatchEvent(new CustomEvent("rssx:counts-changed"));
  }

  const FOLDER_STATE_KEY = "rssx.folderState";

  function loadFolderState() {
    try {
      return JSON.parse(localStorage.getItem(FOLDER_STATE_KEY) || "{}");
    } catch (_e) {
      return {};
    }
  }

  function saveFolderState(state) {
    try {
      localStorage.setItem(FOLDER_STATE_KEY, JSON.stringify(state));
    } catch (_e) {
      // quota or disabled storage — ignore
    }
  }

  function applyFolderState(root) {
    const state = loadFolderState();
    const nodes = (root || document).querySelectorAll("details[data-folder-id]");
    nodes.forEach((d) => {
      const id = d.getAttribute("data-folder-id");
      if (Object.prototype.hasOwnProperty.call(state, id)) {
        d.open = !!state[id];
      }
    });
  }

  function bindFolderToggles(root) {
    const nodes = (root || document).querySelectorAll("details[data-folder-id]");
    nodes.forEach((d) => {
      d.addEventListener("toggle", () => {
        const id = d.getAttribute("data-folder-id");
        const state = loadFolderState();
        state[id] = d.open;
        saveFolderState(state);
      });
    });
  }

  function refreshSidebar() {
    const params = new URLSearchParams(window.location.search);
    params.delete("unread");
    fetch(`/sidebar?${params.toString()}`)
      .then((r) => r.text())
      .then((html) => {
        const tmp = document.createElement("template");
        tmp.innerHTML = html.trim();
        const next = tmp.content.firstElementChild;
        const cur = document.getElementById("sidebar");
        if (cur && next) {
          applyFolderState(next);
          cur.replaceWith(next);
          bindFolderToggles(next);
        }
      });
  }

  function replaceEntry(entryEl, html) {
    const tmp = document.createElement("template");
    tmp.innerHTML = html.trim();
    const next = tmp.content.firstElementChild;
    if (!next) return;
    // Preserve current expanded state body.
    const oldBody = entryEl.querySelector(".entry-body");
    const newBody = next.querySelector(".entry-body");
    if (oldBody && newBody && !oldBody.hidden) {
      newBody.innerHTML = oldBody.innerHTML;
      newBody.hidden = false;
      next.classList.add("expanded");
    }
    if (entryEl.classList.contains("selected")) next.classList.add("selected");
    entryEl.replaceWith(next);
  }

  function toggleExpand(entryEl) {
    const body = entryEl.querySelector(".entry-body");
    if (!body) return;
    clearAutoRead();
    if (body.hidden) {
      const id = entryEl.dataset.entryId;
      if (!body.innerHTML.trim()) {
        body.innerHTML = "<p>読み込み中…</p>";
        fetch(`/entries/${id}`)
          .then((r) => r.text())
          .then((html) => {
            body.innerHTML = html;
          });
      }
      body.hidden = false;
      entryEl.classList.add("expanded");
      if (!entryEl.classList.contains("read")) {
        autoReadTimer = setTimeout(() => markRead(entryEl, true), READ_DELAY_MS);
      }
    } else {
      body.hidden = true;
      entryEl.classList.remove("expanded");
    }
  }

  function toggleRead(entryEl) {
    markRead(entryEl, !entryEl.classList.contains("read"));
  }

  function toggleStar(entryEl) {
    const id = entryEl.dataset.entryId;
    fetch(`/entries/${id}/star`, { method: "POST" })
      .then((r) => r.text())
      .then((html) => {
        replaceEntry(entryEl, html);
        notifyCountsChanged();
      });
  }

  function openOriginal(entryEl) {
    const url = entryEl.dataset.url;
    if (url) window.open(url, "_blank", "noopener,noreferrer");
  }

  function navItems() {
    const sb = document.querySelector(".sidebar");
    if (!sb) return [];
    const items = [];
    sb.querySelectorAll("a.sidebar-link, a.folder-link, a.feed-link").forEach((a) => {
      let url;
      try {
        url = new URL(a.getAttribute("href") || "", location.origin);
      } catch (_e) {
        return;
      }
      const scope = url.searchParams.get("scope");
      if (!scope) return;
      // Hidden by a collapsed ancestor <details>: offsetParent is null because
      // the UA stylesheet hides non-summary children of closed <details>.
      if (a.offsetParent === null) return;
      items.push({
        el: a,
        scope: scope,
        folder: url.searchParams.get("folder"),
        feed: url.searchParams.get("feed"),
      });
    });
    return items;
  }

  function currentNavIndex(items) {
    const params = new URLSearchParams(location.search);
    const scope = params.get("scope") || "all";
    const folder = params.get("folder");
    const feed = params.get("feed");
    let idx = items.findIndex((it) => {
      if (it.scope !== scope) return false;
      if (scope === "folder") return it.folder === folder;
      if (scope === "feed") return it.feed === feed;
      return true;
    });
    if (idx >= 0) return idx;
    if (scope === "feed" && feed != null) {
      const parentId = currentFolderIdFromUrl();
      if (parentId != null) {
        idx = items.findIndex((it) => it.scope === "folder" && it.folder === parentId);
      }
    }
    return idx;
  }

  function navItem(delta) {
    const items = navItems();
    if (!items.length) return;
    let idx = currentNavIndex(items);
    if (idx < 0) idx = delta > 0 ? 0 : items.length - 1;
    else idx = (idx + delta + items.length) % items.length;
    location.href = items[idx].el.getAttribute("href");
  }

  function currentFolderIdFromUrl() {
    const params = new URLSearchParams(location.search);
    const scope = params.get("scope");
    if (scope === "folder") return params.get("folder");
    if (scope === "orphan") return "__orphan";
    if (scope === "feed") {
      const fid = params.get("feed");
      const link = Array.from(document.querySelectorAll(".sidebar .feed-link")).find((a) => {
        try {
          return new URL(a.href, location.origin).searchParams.get("feed") === fid;
        } catch (_e) {
          return false;
        }
      });
      const det = link && link.closest("details[data-folder-id]");
      return det ? det.getAttribute("data-folder-id") : null;
    }
    return null;
  }

  function toggleCurrentFolder() {
    const id = currentFolderIdFromUrl();
    if (id == null) return;
    const det = document.querySelector(`details[data-folder-id="${CSS.escape(id)}"]`);
    if (det) det.open = !det.open;
  }

  function focusSearch() {
    const el = document.getElementById("searchbox");
    if (el) {
      el.focus();
      el.select();
    }
  }

  function refresh() {
    const form = document.querySelector('form[action="/refresh"]');
    if (form) form.submit();
  }

  document.addEventListener("click", (ev) => {
    const row = ev.target.closest(".entry-row");
    if (!row || ev.target.closest(".star")) return;
    const entryEl = row.parentElement;
    const list = entries();
    selectedIndex = list.indexOf(entryEl);
    list.forEach((el, i) => {
      el.classList.toggle("selected", i === selectedIndex);
      if (i !== selectedIndex) collapse(el);
    });
    toggleExpand(entryEl);
  });

  document.addEventListener("keydown", (ev) => {
    if (isTyping()) {
      if (ev.key === "Escape") ev.target.blur();
      return;
    }
    if (ev.shiftKey && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
      // Use ev.code for layout-independent sidebar shortcuts (non-Latin / IME).
      switch (ev.code) {
        case "KeyJ":
          ev.preventDefault();
          navItem(1);
          return;
        case "KeyK":
          ev.preventDefault();
          navItem(-1);
          return;
        case "KeyX":
          ev.preventDefault();
          toggleCurrentFolder();
          return;
      }
    }
    const list = entries();
    const current = selectedIndex >= 0 ? list[selectedIndex] : null;
    switch (ev.key) {
      case "j":
        ev.preventDefault();
        select(selectedIndex < 0 ? 0 : selectedIndex + 1, { expand: true });
        break;
      case "k":
        ev.preventDefault();
        select(selectedIndex < 0 ? 0 : selectedIndex - 1, { expand: true });
        break;
      case "o":
      case "Enter":
        if (current) {
          ev.preventDefault();
          toggleExpand(current);
        }
        break;
      case "m":
        if (current) {
          ev.preventDefault();
          toggleRead(current);
        }
        break;
      case "f":
        if (current) {
          ev.preventDefault();
          toggleStar(current);
        }
        break;
      case "v":
        if (current) {
          ev.preventDefault();
          openOriginal(current);
        }
        break;
      case "r":
        ev.preventDefault();
        refresh();
        break;
      case "/":
        ev.preventDefault();
        focusSearch();
        break;
      case "g":
        ev.preventDefault();
        select(0, { expand: false });
        break;
      case "G":
        ev.preventDefault();
        select(entries().length - 1, { expand: false });
        break;
    }
  });

  document.body.addEventListener("rssx:counts-changed", refreshSidebar);

  document.addEventListener("DOMContentLoaded", () => {
    applyFolderState(document);
    bindFolderToggles(document);
    const list = entries();
    if (list.length > 0) {
      // Select first row but don't auto-expand on load.
      list[0].classList.add("selected");
      selectedIndex = 0;
    }
  });
})();
