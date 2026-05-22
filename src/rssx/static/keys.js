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

  function select(index, opts = {}) {
    const list = entries();
    if (list.length === 0) return;
    index = Math.max(0, Math.min(list.length - 1, index));
    list.forEach((el, i) => el.classList.toggle("selected", i === index));
    selectedIndex = index;
    const el = list[index];
    el.scrollIntoView({ block: "nearest", behavior: "smooth" });
    if (opts.expand && !el.classList.contains("expanded")) {
      toggleExpand(el);
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
      .then((html) => replaceEntry(entryEl, html));
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
      .then((html) => replaceEntry(entryEl, html));
  }

  function openOriginal(entryEl) {
    const url = entryEl.dataset.url;
    if (url) window.open(url, "_blank", "noopener,noreferrer");
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
    list.forEach((el, i) => el.classList.toggle("selected", i === selectedIndex));
    toggleExpand(entryEl);
  });

  document.addEventListener("keydown", (ev) => {
    if (isTyping()) {
      if (ev.key === "Escape") ev.target.blur();
      return;
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

  document.addEventListener("DOMContentLoaded", () => {
    const list = entries();
    if (list.length > 0) {
      // Select first row but don't auto-expand on load.
      list[0].classList.add("selected");
      selectedIndex = 0;
    }
  });
})();
