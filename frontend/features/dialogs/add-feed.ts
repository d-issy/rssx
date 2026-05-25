import { DomainEvent, dispatch } from "../../lib/events";
import { ajax } from "../../lib/htmx";
import { postForm } from "../../lib/http";
import { toast } from "../../lib/toast";

function getDialog(): HTMLDialogElement | null {
  return document.getElementById("add-feed-dialog") as HTMLDialogElement | null;
}

function getBody(): HTMLElement | null {
  return document.getElementById("add-feed-body");
}

function isOpen(): boolean {
  return getDialog()?.open ?? false;
}

async function loadContent(): Promise<void> {
  const body = getBody();
  if (!body) return;
  body.innerHTML = '<p class="add-feed-loading">読み込み中…</p>';
  await ajax("GET", "/add-feed", { target: "#add-feed-body", swap: "innerHTML" });
}

async function openDialog(): Promise<void> {
  const dlg = getDialog();
  if (!dlg || dlg.open) return;
  dlg.showModal();
  await loadContent();
  const body = getBody();
  body?.querySelector<HTMLInputElement>("input[name='url']")?.focus();
}

function closeDialog(): void {
  const dlg = getDialog();
  if (dlg?.open) dlg.close();
  const body = getBody();
  if (body) body.innerHTML = "";
}

function clearError(form: HTMLElement): void {
  form.querySelectorAll(".add-feed-error").forEach((e) => e.remove());
}

function showError(form: HTMLElement, message: string): void {
  clearError(form);
  const urlField = form.querySelector<HTMLElement>(".add-feed-field");
  const err = document.createElement("p");
  err.className = "add-feed-error";
  err.textContent = message;
  (urlField ?? form).after(err);
}

function bindForm(root: HTMLElement): void {
  const form = root.querySelector<HTMLFormElement>("#add-feed-form");
  if (!form) return;
  const select = form.querySelector<HTMLSelectElement>("select[name='folder_id']");
  const newWrap = form.querySelector<HTMLElement>(".add-feed-new-folder");
  const newInput = newWrap?.querySelector<HTMLInputElement>("input[name='new_folder_name']");

  const syncNewFolder = () => {
    if (!select || !newWrap || !newInput) return;
    if (select.value === "__new") {
      newWrap.hidden = false;
      newInput.required = true;
      newInput.focus();
    } else {
      newWrap.hidden = true;
      newInput.required = false;
      newInput.value = "";
    }
  };
  select?.addEventListener("change", syncNewFolder);
  syncNewFolder();

  form.querySelector(".add-feed-close")?.addEventListener("click", () => closeDialog());
  form.querySelector(".add-feed-cancel")?.addEventListener("click", () => closeDialog());

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    clearError(form);
    const data = new FormData(form);
    const submitBtn = form.querySelector<HTMLButtonElement>(".add-feed-submit");
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "追加中…";
    }
    try {
      const res = await postForm("/feeds", data);
      if (!res.ok) {
        let msg = `フィードを追加できませんでした (HTTP ${res.status})`;
        const text = await res.text();
        try {
          const body = JSON.parse(text) as { detail?: unknown };
          if (typeof body?.detail === "string") msg = body.detail;
        } catch {
          if (text && text.length < 200) msg = text;
        }
        showError(form, msg);
        return;
      }
      closeDialog();
      dispatch(DomainEvent.COUNTS_CHANGED);
      toast("フィードを追加しました");
      dispatch(DomainEvent.FEED_ADDED);
    } catch (err) {
      showError(form, `通信エラー: ${(err as Error).message}`);
    } finally {
      if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.textContent = "追加";
      }
    }
  });
}

function bindDialog(): void {
  const dlg = getDialog();
  if (!dlg) return;
  dlg.addEventListener("click", (ev) => {
    if (ev.target === dlg) closeDialog();
  });
  dlg.addEventListener("htmx:afterSwap", (ev) => {
    const target = (ev as Event & { target: Element }).target;
    if (target.id === "add-feed-body") bindForm(target as HTMLElement);
  });
}

export function install(): void {
  document.addEventListener("DOMContentLoaded", bindDialog);
  // Delegated so the button survives sidebar HTMX swaps.
  document.addEventListener("click", (ev) => {
    const btn = (ev.target as HTMLElement | null)?.closest<HTMLElement>("#add-feed-open");
    if (!btn) return;
    ev.preventDefault();
    void openDialog();
  });
}

export { isOpen };
