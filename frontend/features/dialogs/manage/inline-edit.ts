import { DomainEvent, dispatch } from "../../../lib/events";
import { process } from "../../../lib/htmx";
import { postForm } from "../../../lib/http";
import { refresh as refreshRelativeTimes } from "../../../lib/relative-time";
import { toast } from "../../../lib/toast";

import { syncAfterFolderMutation } from "./sync";

function flashSaved(target: Element | null | undefined): void {
  if (!target) return;
  const host =
    target instanceof HTMLElement ? target : (target.parentElement as HTMLElement | null);
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

// dblclick → input → blur/Enter saves
export function beginEdit(span: HTMLElement): void {
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
      const res = await postForm(url, form);
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
          process(newRow as Element);
          refreshRelativeTimes(newRow as Element);
          const editable = (newRow as Element).querySelector<HTMLElement>(
            `.manage-editable[data-edit-field="${field}"]`,
          );
          flashSaved(editable);
          dispatch(DomainEvent.COUNTS_CHANGED);
          if (isFolderRename) syncAfterFolderMutation();
          return;
        }
      }
      restore(value);
      dispatch(DomainEvent.COUNTS_CHANGED);
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
