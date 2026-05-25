import { process, trigger } from "../../../lib/htmx";

export type FolderRef = { id: string; name: string };

function updateFolderFilterLabel(root: HTMLElement): void {
  const label = root.querySelector<HTMLElement>(".manage-folder-filter-label");
  if (!label) return;
  const boxes = root.querySelectorAll<HTMLInputElement>("input[name='folders']");
  const total = boxes.length;
  const checked = Array.from(boxes).filter((b) => b.checked);
  if (checked.length === total) label.textContent = "フォルダ: すべて";
  else if (checked.length === 0) label.textContent = "フォルダ: なし";
  else if (checked.length === 1) {
    const name = checked[0].parentElement?.querySelector("span")?.textContent?.trim() ?? "(1件)";
    label.textContent = `フォルダ: ${name}`;
  } else label.textContent = `フォルダ: ${checked.length}件`;
}

export function fireFilterRequest(root: HTMLElement): void {
  // Find any folder checkbox (they all share the same hx-get/target).
  const probe = root.querySelector<HTMLInputElement>("input[name='folders']");
  if (!probe) return;
  // Trigger HTMX once on the probe element — its hx-include picks up
  // all checkboxes' current state plus the search input.
  if (typeof htmx !== "undefined") {
    trigger(probe, "change");
  } else {
    probe.dispatchEvent(new Event("change", { bubbles: true }));
  }
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
export function syncFolderFilter(folders: FolderRef[]): void {
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
  present.forEach((row, id) => {
    if (!wanted.has(id)) row.remove();
  });
  for (const folder of folders) {
    const row = present.get(folder.id);
    if (row) {
      const nameEl = row.querySelector<HTMLElement>(".manage-folder-filter-name");
      if (nameEl && nameEl.textContent !== folder.name) nameEl.textContent = folder.name;
    } else {
      const div = buildFilterCheckbox(folder);
      popover.appendChild(div);
      process(div);
    }
  }
  updateFolderFilterLabel(filter);
}

export function bindFolderFilter(root: HTMLElement): void {
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

  const selectAllBtn = root.querySelector<HTMLButtonElement>("[data-folder-select-all]");
  const selectNoneBtn = root.querySelector<HTMLButtonElement>("[data-folder-select-none]");
  const setAll = (checked: boolean) => {
    root.querySelectorAll<HTMLInputElement>("input[name='folders']").forEach((box) => {
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
  // Checkbox click = standard toggle.
  root.addEventListener("click", (ev) => {
    const target = ev.target as HTMLElement;
    if (target.tagName === "INPUT") return;
    const row = target.closest<HTMLElement>("[data-folder-row]");
    if (!row || !root.contains(row)) return;
    const myBox = row.querySelector<HTMLInputElement>("input[name='folders']");
    if (!myBox) return;
    ev.preventDefault();
    root.querySelectorAll<HTMLInputElement>("input[name='folders']").forEach((box) => {
      box.checked = box === myBox;
    });
    updateFolderFilterLabel(root);
    fireFilterRequest(root);
  });

  updateFolderFilterLabel(root);
}

// Outside-click listener is installed once on document; it resolves the live
// popover/root via querySelector to avoid leaking listeners bound to stale
// (detached) roots across htmx:afterSwap.
export function installFolderFilterOutsideClick(): void {
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
