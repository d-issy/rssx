import { DomainEvent, dispatch } from "../../../lib/events";
import { process } from "../../../lib/htmx";
import { postForm } from "../../../lib/http";
import { toast } from "../../../lib/toast";

import { syncAfterFolderMutation } from "./sync";

export function startFolderAdd(panel: HTMLElement): void {
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
      const res = await postForm("/folders", form);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const html = await res.text();
      const listWrap = panel.querySelector<HTMLElement>("#manage-folder-list");
      if (listWrap) {
        listWrap.innerHTML = html;
        process(listWrap);
        syncAfterFolderMutation();
      }
      dispatch(DomainEvent.COUNTS_CHANGED);
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
