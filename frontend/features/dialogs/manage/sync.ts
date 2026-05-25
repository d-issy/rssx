import { getHtml } from "../../../lib/http";
import { process } from "../../../lib/htmx";

import { fireFilterRequest, syncFolderFilter, type FolderRef } from "./folder-filter";

export function collectFolders(): FolderRef[] {
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

// After any folder mutation (add / rename / delete), reconcile the rest of the
// dialog: filter pulldown checkboxes get rebuilt from the current folder list,
// and the feed list is re-fetched so each row's <select> options + visible
// rows reflect the new folder set (relevant for renames and cascade deletes).
export function syncAfterFolderMutation(): void {
  const folders = collectFolders();
  syncFolderFilter(folders);
  const filter = document.querySelector<HTMLElement>("[data-folder-filter]");
  if (filter) fireFilterRequest(filter);
}

// After a feed mutation that can change folder counts (folder reassignment,
// deletion), re-fetch the folder list so each row's "feed count" column stays
// in sync. The folder tab might not be visible right now, but updating its
// DOM is cheap.
export async function syncFolderCountsAfterFeedChange(): Promise<void> {
  const wrap = document.querySelector<HTMLElement>("#manage-folder-list");
  if (!wrap) return;
  try {
    wrap.innerHTML = await getHtml("/manage/folders");
    process(wrap);
  } catch {
    // silent — folder count refresh is a nice-to-have
  }
}
