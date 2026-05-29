import { parseFragment } from "../../lib/dom";
import { DomainEvent, listen } from "../../lib/events";

const FOLDER_STATE_KEY = "rssx.folderState";

type FolderState = Record<string, boolean>;

function loadFolderState(): FolderState {
  try {
    return JSON.parse(localStorage.getItem(FOLDER_STATE_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveFolderState(state: FolderState): void {
  try {
    localStorage.setItem(FOLDER_STATE_KEY, JSON.stringify(state));
  } catch {
    // quota exceeded or storage disabled — ignore
  }
}

function applyFolderState(root: ParentNode): void {
  const state = loadFolderState();
  root.querySelectorAll<HTMLDetailsElement>("details[data-folder-id]").forEach((d) => {
    const id = d.getAttribute("data-folder-id");
    if (id != null && Object.prototype.hasOwnProperty.call(state, id)) {
      d.open = !!state[id];
    }
  });
}

function bindFolderToggles(root: ParentNode): void {
  root.querySelectorAll<HTMLDetailsElement>("details[data-folder-id]").forEach((d) => {
    d.addEventListener("toggle", () => {
      const id = d.getAttribute("data-folder-id");
      if (id == null) return;
      const state = loadFolderState();
      state[id] = d.open;
      saveFolderState(state);
    });
  });
}

async function refreshSidebar(): Promise<void> {
  const url = new URL("/sidebar", location.origin);
  const params = new URLSearchParams(window.location.search);
  params.delete("unread");
  params.forEach((value, key) => url.searchParams.append(key, value));
  const res = await fetch(url);
  const html = await res.text();
  const next = parseFragment<HTMLElement>(html);
  const cur = document.getElementById("sidebar");
  if (cur && next) {
    applyFolderState(next);
    cur.replaceWith(next);
    bindFolderToggles(next);
  }
}

export function currentFolderIdFromUrl(): string | null {
  const params = new URLSearchParams(location.search);
  const scope = params.get("scope");
  if (scope === "folder") return params.get("folder");
  // Orphan feeds live at sidebar root (no enclosing <details>). There is no
  // collapsible group to identify.
  if (scope === "feed") {
    const fid = params.get("feed");
    const link = Array.from(
      document.querySelectorAll<HTMLAnchorElement>(".sidebar .feed-link"),
    ).find((a) => {
      try {
        return new URL(a.href, location.origin).searchParams.get("feed") === fid;
      } catch {
        return false;
      }
    });
    const det = link ? link.closest<HTMLDetailsElement>("details[data-folder-id]") : null;
    return det ? det.getAttribute("data-folder-id") : null;
  }
  return null;
}

export function toggleCurrentFolder(): void {
  const id = currentFolderIdFromUrl();
  if (id == null) return;
  const det = document.querySelector<HTMLDetailsElement>(
    `details[data-folder-id="${CSS.escape(id)}"]`,
  );
  if (det) det.open = !det.open;
}

export function install(): void {
  document.addEventListener("DOMContentLoaded", () => {
    applyFolderState(document);
    bindFolderToggles(document);
  });
  listen(DomainEvent.COUNTS_CHANGED, refreshSidebar);
}
