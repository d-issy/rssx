import { isTyping } from "./dom";
import {
  getSelected,
  openOriginal,
  selectFirst,
  selectLast,
  selectRelative,
  toggleRead,
  toggleStar,
} from "./entries";
import { toggleCurrentFolder } from "./folders";
import { isHelpOpen, toggleHelp } from "./help-dialog";
import { navItem } from "./sidebar-nav";

function focusSearch(): void {
  const el = document.getElementById("searchbox") as HTMLInputElement | null;
  if (el) {
    el.focus();
    el.select();
  }
}

function refresh(): void {
  const form = document.querySelector<HTMLFormElement>('form[action="/refresh"]');
  if (form) form.submit();
}

function handleSidebarShortcut(ev: KeyboardEvent): boolean {
  if (!ev.shiftKey || ev.ctrlKey || ev.metaKey || ev.altKey) return false;
  switch (ev.code) {
    case "KeyJ":
      navItem(1);
      return true;
    case "KeyK":
      navItem(-1);
      return true;
    case "KeyX":
      toggleCurrentFolder();
      return true;
    default:
      return false;
  }
}

function handleEntryShortcut(ev: KeyboardEvent): boolean {
  const current = getSelected();
  switch (ev.key) {
    case "j":
      selectRelative(1, { expand: true });
      return true;
    case "k":
      selectRelative(-1, { expand: true });
      return true;
    case "g":
      selectFirst();
      return true;
    case "G":
      selectLast();
      return true;
    case "m":
      if (current) toggleRead(current);
      return current != null;
    case "f":
      if (current) toggleStar(current);
      return current != null;
    case "v":
      if (current) openOriginal(current);
      return current != null;
    case "r":
      refresh();
      return true;
    case "/":
      focusSearch();
      return true;
    default:
      return false;
  }
}

export function install(): void {
  document.addEventListener("keydown", (ev) => {
    if (isTyping()) {
      if (ev.key === "Escape") (ev.target as HTMLElement | null)?.blur();
      return;
    }
    if (ev.key === "?") {
      ev.preventDefault();
      toggleHelp();
      return;
    }
    // While help is open, let the <dialog> handle Esc itself; ignore other keys.
    if (isHelpOpen()) return;
    if (handleSidebarShortcut(ev)) {
      ev.preventDefault();
      return;
    }
    if (handleEntryShortcut(ev)) {
      ev.preventDefault();
    }
  });
}
