import { DomainEvent, listen } from "../../../lib/events";
import { ajax } from "../../../lib/htmx";
import { refresh as refreshRelativeTimes } from "../../../lib/relative-time";
import { toast } from "../../../lib/toast";

import { copyToClipboard } from "./clipboard";
import { showFeedDeleteConfirm, showFolderDeleteConfirm } from "./delete-confirm";
import { startFolderAdd } from "./folder-add";
import {
  bindFolderFilter,
  fireFilterRequest,
  installFolderFilterOutsideClick,
} from "./folder-filter";
import { beginEdit } from "./inline-edit";
import { syncAfterFolderMutation, syncFolderCountsAfterFeedChange } from "./sync";

function getDialog(): HTMLDialogElement | null {
  return document.getElementById("manage-dialog") as HTMLDialogElement | null;
}

function getBody(): HTMLElement | null {
  return document.getElementById("manage-dialog-body");
}

export function isOpen(): boolean {
  return getDialog()?.open ?? false;
}

async function loadContent(): Promise<void> {
  const body = getBody();
  if (!body) return;
  body.removeAttribute("data-empty");
  body.innerHTML = '<p class="manage-loading">読み込み中…</p>';
  await ajax("GET", "/manage", { target: "#manage-dialog-body", swap: "innerHTML" });
  refreshRelativeTimes(body);
}

export async function openDialog(): Promise<void> {
  const dlg = getDialog();
  if (!dlg || dlg.open) return;
  dlg.showModal();
  const body = getBody();
  if (body && body.hasAttribute("data-empty")) {
    await loadContent();
  }
}

export function closeDialog(): void {
  const dlg = getDialog();
  if (dlg?.open) dlg.close();
}

function switchTab(name: string): void {
  const body = getBody();
  if (!body) return;
  body.querySelectorAll<HTMLButtonElement>(".manage-tab").forEach((btn) => {
    const active = btn.dataset.tab === name;
    btn.classList.toggle("active", active);
    btn.setAttribute("aria-selected", active ? "true" : "false");
  });
  body.querySelectorAll<HTMLElement>(".manage-tab-panel").forEach((panel) => {
    panel.hidden = panel.dataset.panel !== name;
  });
}

function bindBodyDelegation(): void {
  const dlg = getDialog();
  if (!dlg) return;

  dlg.addEventListener("click", (ev) => {
    const target = ev.target as HTMLElement;
    if (target.closest(".manage-dialog-close")) {
      closeDialog();
      return;
    }
    const tab = target.closest<HTMLElement>(".manage-tab");
    if (tab && tab.dataset.tab) {
      switchTab(tab.dataset.tab);
      return;
    }
    const copy = target.closest<HTMLElement>(".manage-copy");
    if (copy && copy.dataset.copy) {
      const text = copy.dataset.copy;
      void copyToClipboard(text).then((ok) => {
        toast(ok ? "URL をコピーしました" : "コピーできませんでした", ok ? "info" : "error");
        return ok;
      });
      return;
    }
    const fdel = target.closest<HTMLButtonElement>("[data-delete-confirm]");
    if (fdel) {
      showFeedDeleteConfirm(fdel);
      return;
    }
    const folderDel = target.closest<HTMLButtonElement>("[data-folder-delete-confirm]");
    if (folderDel) {
      showFolderDeleteConfirm(folderDel);
      return;
    }
    const addFolder = target.closest<HTMLElement>("[data-folder-add]");
    if (addFolder) {
      const panel = addFolder.closest<HTMLElement>(".manage-tab-panel");
      if (panel) startFolderAdd(panel);
      return;
    }
  });

  dlg.addEventListener("dblclick", (ev) => {
    const span = (ev.target as HTMLElement).closest<HTMLElement>(".manage-editable");
    if (span) {
      ev.preventDefault();
      beginEdit(span);
    }
  });

  // backdrop click closes
  dlg.addEventListener("click", (ev) => {
    if (ev.target === dlg) closeDialog();
  });

  // After HTMX swaps inside the dialog body, rebind filter popover & relative times.
  dlg.addEventListener("htmx:afterSwap", (ev) => {
    const target = (ev as Event & { target: Element }).target;
    if (target.id === "manage-dialog-body") {
      const filter = target.querySelector<HTMLElement>("[data-folder-filter]");
      if (filter) bindFolderFilter(filter);
    }
    refreshRelativeTimes(target);
  });

  // NOTE: We cannot use `htmx:afterRequest` on the dialog to detect feed/folder
  // mutations because hx-swap="outerHTML" detaches the source element BEFORE
  // htmx:afterRequest fires. Detached elements don't bubble events. Instead,
  // the server emits custom events via HX-Trigger which HTMX dispatches on
  // document.body; we listen there in install().
}

function isEditingInsideDialog(): boolean {
  const dlg = getDialog();
  if (!dlg || !dlg.open) return false;
  const active = document.activeElement as HTMLElement | null;
  if (!active) return false;
  if (!dlg.contains(active)) return false;
  return active.classList.contains("manage-edit-input");
}

export function install(): void {
  document.addEventListener("DOMContentLoaded", () => {
    bindBodyDelegation();
    installFolderFilterOutsideClick();

    // Server-driven reconciliation events (via HX-Trigger headers). They fire
    // on document.body so they survive detached source elements.
    listen(DomainEvent.FEED_ADDED, () => {
      if (!isOpen()) return;
      const filter = document.querySelector<HTMLElement>("[data-folder-filter]");
      if (filter) fireFilterRequest(filter);
    });
    listen(DomainEvent.FEED_FOLDER_CHANGED, () => {
      if (!isOpen()) return;
      // A feed's folder assignment changed; folder counts need a refresh.
      void syncFolderCountsAfterFeedChange();
    });
    listen(DomainEvent.FOLDER_CHANGED, () => {
      if (!isOpen()) return;
      // A folder was deleted server-side via the HTMX form. Reconcile the
      // filter pulldown and re-fetch the feed list (cascade delete may have
      // removed feeds; detach mode moves feeds to orphan).
      syncAfterFolderMutation();
    });
  });

  // Delegated so the link survives sidebar HTMX swaps.
  document.addEventListener("click", (ev) => {
    const link = (ev.target as HTMLElement | null)?.closest<HTMLAnchorElement>("#manage-open");
    if (!link) return;
    ev.preventDefault();
    void openDialog();
  });

  document.addEventListener(
    "keydown",
    (ev) => {
      if (!isOpen()) return;
      if (ev.key !== "Escape") return;
      if (isEditingInsideDialog()) {
        // The <input> escape handler restores the span. Stop the event so the
        // native <dialog> cancel handler doesn't close the modal.
        ev.preventDefault();
        ev.stopPropagation();
      }
      // otherwise, the <dialog> default closes itself
    },
    true,
  );

  // <dialog> dispatches 'cancel' on Esc that closes the modal. While an inline
  // editor is active, swallow it so only the editor's own Esc handler runs.
  const dlg = getDialog();
  dlg?.addEventListener("cancel", (ev) => {
    if (isEditingInsideDialog()) ev.preventDefault();
  });
}
