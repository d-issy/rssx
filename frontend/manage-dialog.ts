import { dispatchCountsChanged } from "./dom";
import { refresh as refreshRelativeTimes } from "./relative-time";
import { toast } from "./toast";

declare const htmx: {
  ajax: (method: string, url: string, opts: Record<string, unknown>) => Promise<void>;
  process: (root: Element | Document) => void;
};

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
  await htmx.ajax("GET", "/manage", { target: "#manage-dialog-body", swap: "innerHTML" });
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

function flashSaved(target: Element | null | undefined): void {
  if (!target) return;
  const host = target instanceof HTMLElement ? target : (target.parentElement as HTMLElement | null);
  if (!host) return;
  const mark = document.createElement("span");
  mark.className = "manage-saved-flash";
  mark.textContent = "✓";
  host.appendChild(mark);
  requestAnimationFrame(() => mark.classList.add("show"));
  setTimeout(() => {
    mark.classList.remove("show");
    setTimeout(() => mark.remove(), 400);
  }, 800);
}

// --- inline editable (double-click → input → blur/Enter saves) ---

function beginEdit(span: HTMLElement): void {
  if (span.dataset.editing === "1") return;
  span.dataset.editing = "1";
  const original = span.textContent ?? "";
  const url = span.dataset.editUrl;
  const field = span.dataset.editField;
  if (!url || !field) return;

  const input = document.createElement("input");
  input.type = "text";
  input.value = original;
  input.className = "manage-edit-input";
  span.replaceWith(input);
  input.focus();
  input.select();

  let settled = false;
  const restore = (text: string) => {
    if (settled) return;
    settled = true;
    const next = document.createElement("span");
    next.className = span.className;
    next.dataset.editField = field;
    next.dataset.editUrl = url;
    next.title = span.title;
    next.textContent = text;
    input.replaceWith(next);
  };

  const commit = async () => {
    if (settled) return;
    const value = input.value.trim();
    if (value === "" || value === original) {
      restore(original);
      return;
    }
    settled = true;
    const form = new FormData();
    form.append(field, value);
    try {
      const res = await fetch(url, {
        method: "POST",
        body: form,
        headers: { "HX-Request": "true" },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const html = (await res.text()).trim();
      const row = input.closest("[id^='manage-feed-'], [id^='manage-folder-']");
      const isFolderRename = url.includes("/folders/") && url.endsWith("/rename");
      if (html && row) {
        const tmp = document.createElement("template");
        tmp.innerHTML = html;
        const newRow = tmp.content.firstElementChild;
        if (newRow) {
          row.replaceWith(newRow);
          htmx.process(newRow as Element);
          refreshRelativeTimes(newRow as Element);
          const editable = (newRow as Element).querySelector<HTMLElement>(
            `.manage-editable[data-edit-field="${field}"]`,
          );
          flashSaved(editable);
          dispatchCountsChanged();
          if (isFolderRename) syncAfterFolderMutation();
          return;
        }
      }
      restore(value);
      dispatchCountsChanged();
      if (isFolderRename) syncAfterFolderMutation();
    } catch (err) {
      toast(`保存に失敗しました: ${(err as Error).message}`, "error");
      restore(original);
    }
  };

  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      input.blur();
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      ev.stopPropagation();
      settled = true;
      restore(original);
    }
  });
  input.addEventListener("blur", commit);
}

// --- URL copy ---

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand("copy");
      ta.remove();
      return ok;
    } catch {
      return false;
    }
  }
}

// --- feed delete confirm (2-button inline) ---

function showFeedDeleteConfirm(btn: HTMLButtonElement): void {
  const host = btn.closest<HTMLElement>("[data-confirm-host]");
  if (!host) return;
  const original = host.innerHTML;
  host.innerHTML = `
    <span class="manage-delete-prompt">本当に削除しますか？</span>
    <button type="button" class="manage-delete-confirm danger" data-feed-delete-do>削除する</button>
    <button type="button" class="manage-delete-cancel" data-feed-delete-cancel>キャンセル</button>
  `;
  host.querySelector("[data-feed-delete-do]")?.addEventListener("click", () => {
    const form = host.closest("tr")?.querySelector<HTMLFormElement>(".manage-delete-form");
    if (form) form.requestSubmit();
  });
  host.querySelector("[data-feed-delete-cancel]")?.addEventListener("click", () => {
    host.innerHTML = original;
  });
}

// --- folder delete confirm (3-button or 1-button depending on contents) ---

function showFolderDeleteConfirm(btn: HTMLButtonElement): void {
  const host = btn.closest<HTMLElement>("[data-confirm-host]");
  const row = btn.closest<HTMLElement>(".manage-folder-row");
  if (!host || !row) return;
  const count = parseInt(row.dataset.folderFeedCount ?? "0", 10) || 0;
  const original = host.innerHTML;
  const form = row.querySelector<HTMLFormElement>(".manage-folder-delete-form");
  const modeInput = form?.querySelector<HTMLInputElement>("input[name='mode']");

  if (count === 0) {
    host.innerHTML = `
      <span class="manage-delete-prompt">本当に削除しますか？</span>
      <button type="button" class="manage-delete-confirm danger" data-folder-delete-do>削除する</button>
      <button type="button" class="manage-delete-cancel" data-folder-delete-cancel>キャンセル</button>
    `;
    host.querySelector("[data-folder-delete-do]")?.addEventListener("click", () => {
      if (modeInput) modeInput.value = "detach";
      form?.requestSubmit();
    });
  } else {
    host.innerHTML = `
      <span class="manage-delete-prompt">中のフィード（${count}件）はどうしますか？</span>
      <button type="button" class="manage-delete-confirm" data-folder-detach>未分類に移して削除</button>
      <button type="button" class="manage-delete-confirm danger" data-folder-cascade>フィードごと全削除</button>
      <button type="button" class="manage-delete-cancel" data-folder-delete-cancel>キャンセル</button>
    `;
    host.querySelector("[data-folder-detach]")?.addEventListener("click", () => {
      if (modeInput) modeInput.value = "detach";
      form?.requestSubmit();
    });
    host.querySelector("[data-folder-cascade]")?.addEventListener("click", () => {
      if (modeInput) modeInput.value = "cascade";
      form?.requestSubmit();
    });
  }
  host.querySelector("[data-folder-delete-cancel]")?.addEventListener("click", () => {
    host.innerHTML = original;
  });
}

// --- folder add inline ---

function startFolderAdd(panel: HTMLElement): void {
  const wrap = panel.querySelector<HTMLElement>("#manage-folder-list");
  if (!wrap) return;
  let table = wrap.querySelector<HTMLTableElement>(".manage-folder-table");
  if (!table) {
    wrap.innerHTML = `
      <table class="manage-folder-table">
        <thead><tr>
          <th class="col-name">フォルダ名</th>
          <th class="col-count">フィード数</th>
          <th class="col-actions" aria-label="操作"></th>
        </tr></thead>
        <tbody></tbody>
      </table>
    `;
    table = wrap.querySelector<HTMLTableElement>(".manage-folder-table");
  }
  const tbody = table?.querySelector<HTMLTableSectionElement>("tbody");
  if (!tbody) return;
  if (tbody.querySelector(".manage-folder-row-new")) {
    tbody.querySelector<HTMLInputElement>(".manage-folder-row-new input")?.focus();
    return;
  }
  const tr = document.createElement("tr");
  tr.className = "manage-folder-row manage-folder-row-new";
  tr.innerHTML = `
    <td class="col-name"><input type="text" class="manage-edit-input" placeholder="フォルダ名" autocomplete="off"></td>
    <td class="col-count">—</td>
    <td class="col-actions"></td>
  `;
  tbody.prepend(tr);
  const input = tr.querySelector<HTMLInputElement>("input");
  if (!input) return;
  input.focus();
  let settled = false;
  const cancel = () => {
    if (settled) return;
    settled = true;
    tr.remove();
  };
  const submit = async () => {
    if (settled) return;
    const value = input.value.trim();
    if (!value) {
      cancel();
      return;
    }
    settled = true;
    input.disabled = true;
    const form = new FormData();
    form.append("name", value);
    try {
      const res = await fetch("/folders", {
        method: "POST",
        body: form,
        headers: { "HX-Request": "true" },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const html = await res.text();
      const listWrap = panel.querySelector<HTMLElement>("#manage-folder-list");
      if (listWrap) {
        listWrap.innerHTML = html;
        htmx.process(listWrap);
        syncAfterFolderMutation();
      }
      dispatchCountsChanged();
    } catch (err) {
      toast(`フォルダ作成に失敗しました: ${(err as Error).message}`, "error");
      tr.remove();
    }
  };
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") {
      ev.preventDefault();
      void submit();
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      ev.stopPropagation();
      cancel();
    }
  });
  input.addEventListener("blur", () => {
    if (settled) return;
    if (input.value.trim()) void submit();
    else cancel();
  });
}

type FolderRef = { id: string; name: string };

function collectFolders(): FolderRef[] {
  const listWrap = document.querySelector<HTMLElement>("#manage-folder-list");
  if (!listWrap) return [];
  const out: FolderRef[] = [];
  listWrap.querySelectorAll<HTMLElement>(".manage-folder-row").forEach((row) => {
    if (row.classList.contains("manage-folder-row-new")) return;
    const id = row.getAttribute("data-folder-id");
    const name = row.querySelector(".manage-folder-name")?.textContent?.trim() ?? "";
    if (id) out.push({ id, name });
  });
  return out;
}

function buildFilterCheckbox(folder: FolderRef): HTMLElement {
  const div = document.createElement("div");
  div.className = "manage-folder-filter-item";
  div.setAttribute("data-folder-row", "");
  div.innerHTML = `
    <input type="checkbox" name="folders" value="${folder.id}" checked
      hx-get="/manage/feeds" hx-trigger="change"
      hx-target="#manage-feed-list"
      hx-include="#manage-search-input, [data-folder-filter] [name='folders']">
    <span class="manage-folder-filter-name"></span>
  `;
  const nameEl = div.querySelector<HTMLElement>(".manage-folder-filter-name");
  if (nameEl) nameEl.textContent = folder.name;
  return div;
}

// Full bidirectional sync of the folder filter pulldown to match the current
// folder set: removes orphaned checkboxes, updates renamed ones, appends new
// ones. Preserves the orphan checkbox and the action buttons header.
function syncFolderFilter(folders: FolderRef[]): void {
  const filter = document.querySelector<HTMLElement>("[data-folder-filter]");
  const popover = filter?.querySelector<HTMLElement>(".manage-folder-filter-popover");
  if (!filter || !popover) return;
  const wanted = new Map(folders.map((f) => [f.id, f]));
  const present = new Map<string, HTMLElement>();
  popover.querySelectorAll<HTMLElement>("[data-folder-row]").forEach((row) => {
    const box = row.querySelector<HTMLInputElement>("input[name='folders']");
    const v = box?.value;
    if (!v || v === "__orphan") return;
    present.set(v, row);
  });
  // Remove rows for folders that no longer exist.
  present.forEach((row, id) => {
    if (!wanted.has(id)) row.remove();
  });
  // Update existing names; append missing.
  for (const folder of folders) {
    const row = present.get(folder.id);
    if (row) {
      const nameEl = row.querySelector<HTMLElement>(".manage-folder-filter-name");
      if (nameEl && nameEl.textContent !== folder.name) nameEl.textContent = folder.name;
    } else {
      const div = buildFilterCheckbox(folder);
      popover.appendChild(div);
      htmx.process(div);
    }
  }
  updateFolderFilterLabel(filter);
}

// After any folder mutation (add / rename / delete), reconcile the rest of the
// dialog: filter pulldown checkboxes get rebuilt from the current folder list,
// and the feed list is re-fetched so each row's <select> options + visible
// rows reflect the new folder set (relevant for renames and cascade deletes).
function syncAfterFolderMutation(): void {
  const folders = collectFolders();
  syncFolderFilter(folders);
  const filter = document.querySelector<HTMLElement>("[data-folder-filter]");
  if (filter) fireFilterRequest(filter);
}

// After a feed mutation that can change folder counts (folder reassignment,
// deletion), re-fetch the folder list so each row's "feed count" column stays
// in sync. The folder tab might not be visible right now, but updating its
// DOM is cheap.
async function syncFolderCountsAfterFeedChange(): Promise<void> {
  const wrap = document.querySelector<HTMLElement>("#manage-folder-list");
  if (!wrap) return;
  try {
    const res = await fetch("/manage/folders", {
      headers: { "HX-Request": "true" },
    });
    if (!res.ok) return;
    wrap.innerHTML = await res.text();
    htmx.process(wrap);
  } catch {
    // silent — folder count refresh is a nice-to-have
  }
}

// --- folder filter popover ---

function updateFolderFilterLabel(root: HTMLElement): void {
  const label = root.querySelector<HTMLElement>(".manage-folder-filter-label");
  if (!label) return;
  const boxes = root.querySelectorAll<HTMLInputElement>("input[name='folders']");
  const total = boxes.length;
  const checked = Array.from(boxes).filter((b) => b.checked);
  if (checked.length === total) label.textContent = "フォルダ: すべて";
  else if (checked.length === 0) label.textContent = "フォルダ: なし";
  else if (checked.length === 1) {
    const name =
      checked[0].parentElement?.querySelector("span")?.textContent?.trim() ?? "(1件)";
    label.textContent = `フォルダ: ${name}`;
  } else label.textContent = `フォルダ: ${checked.length}件`;
}

function fireFilterRequest(root: HTMLElement): void {
  // Find any folder checkbox (they all share the same hx-get/target).
  const probe = root.querySelector<HTMLInputElement>("input[name='folders']");
  if (!probe) return;
  // Trigger HTMX once on the probe element — its hx-include picks up
  // all checkboxes' current state plus the search input.
  if (typeof htmx !== "undefined" && (htmx as unknown as { trigger?: unknown }).trigger) {
    (
      htmx as unknown as {
        trigger: (target: Element, name: string) => void;
      }
    ).trigger(probe, "change");
  } else {
    probe.dispatchEvent(new Event("change", { bubbles: true }));
  }
}

function bindFolderFilter(root: HTMLElement): void {
  const button = root.querySelector<HTMLButtonElement>(".manage-folder-filter-button");
  const popover = root.querySelector<HTMLElement>(".manage-folder-filter-popover");
  if (!button || !popover) return;
  button.addEventListener("click", (ev) => {
    ev.stopPropagation();
    const open = !popover.hidden;
    popover.hidden = open;
    button.setAttribute("aria-expanded", open ? "false" : "true");
  });
  root.addEventListener("change", () => updateFolderFilterLabel(root));
  // NOTE: outside-click listener is installed once on document in install();
  // it resolves the live popover/root via querySelector to avoid leaking
  // listeners bound to stale (detached) roots across htmx:afterSwap.

  const selectAllBtn = root.querySelector<HTMLButtonElement>("[data-folder-select-all]");
  const selectNoneBtn = root.querySelector<HTMLButtonElement>("[data-folder-select-none]");
  const setAll = (checked: boolean) => {
    root
      .querySelectorAll<HTMLInputElement>("input[name='folders']")
      .forEach((box) => {
        box.checked = checked;
      });
    updateFolderFilterLabel(root);
    fireFilterRequest(root);
  };
  selectAllBtn?.addEventListener("click", (ev) => {
    ev.preventDefault();
    setAll(true);
  });
  selectNoneBtn?.addEventListener("click", (ev) => {
    ev.preventDefault();
    setAll(false);
  });

  // Row click (anywhere except the checkbox itself) = solo-select that folder.
  // Checkbox click = standard toggle (handled by browser + hx-trigger="change").
  root.addEventListener("click", (ev) => {
    const target = ev.target as HTMLElement;
    if (target.tagName === "INPUT") return; // let the checkbox toggle naturally
    const row = target.closest<HTMLElement>("[data-folder-row]");
    if (!row || !root.contains(row)) return;
    const myBox = row.querySelector<HTMLInputElement>("input[name='folders']");
    if (!myBox) return;
    ev.preventDefault();
    root
      .querySelectorAll<HTMLInputElement>("input[name='folders']")
      .forEach((box) => {
        box.checked = box === myBox;
      });
    updateFolderFilterLabel(root);
    fireFilterRequest(root);
  });

  updateFolderFilterLabel(root);
}

// --- dialog body event delegation ---

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
  // mutations because hx-swap="outerHTML" detaches the source element (the
  // <select> / form) BEFORE htmx:afterRequest fires. Detached elements don't
  // bubble events. Instead, the server emits custom events via HX-Trigger which
  // HTMX dispatches on document.body. We listen there (see install()).
}

// --- 2-stage Escape ---

function isEditingInsideDialog(): boolean {
  const dlg = getDialog();
  if (!dlg || !dlg.open) return false;
  const active = document.activeElement as HTMLElement | null;
  if (!active) return false;
  if (!dlg.contains(active)) return false;
  return active.classList.contains("manage-edit-input");
}

function installFolderFilterOutsideClick(): void {
  document.addEventListener("click", (ev) => {
    const root = document.querySelector<HTMLElement>("[data-folder-filter]");
    if (!root) return;
    const popover = root.querySelector<HTMLElement>(".manage-folder-filter-popover");
    if (!popover || popover.hidden) return;
    if (!root.contains(ev.target as Node)) {
      popover.hidden = true;
      root
        .querySelector<HTMLButtonElement>(".manage-folder-filter-button")
        ?.setAttribute("aria-expanded", "false");
    }
  });
}

export function install(): void {
  document.addEventListener("DOMContentLoaded", () => {
    bindBodyDelegation();
    installFolderFilterOutsideClick();
    // ---- Server-driven reconciliation events (via HX-Trigger headers) ----
    // These fire on document.body so they survive detached source elements.
    document.body.addEventListener("rssx:feed-added", () => {
      if (!isOpen()) return;
      const filter = document.querySelector<HTMLElement>("[data-folder-filter]");
      if (filter) fireFilterRequest(filter);
    });
    document.body.addEventListener("rssx:feed-folder-changed", () => {
      if (!isOpen()) return;
      // A feed's folder assignment changed (edit / delete / add). Folder counts
      // need a refresh; feed list is already updated by HTMX swap of the row.
      void syncFolderCountsAfterFeedChange();
    });
    document.body.addEventListener("rssx:folder-changed", () => {
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
        return;
      }
      // otherwise, the <dialog> default closes itself
    },
    true,
  );

  // <dialog> dispatches a 'cancel' event on Esc that closes the modal. While
  // an inline editor is active inside the dialog, swallow it so only the
  // editor's own Esc handler runs.
  const dlg = getDialog();
  dlg?.addEventListener("cancel", (ev) => {
    if (isEditingInsideDialog()) ev.preventDefault();
  });
}
