export function showFeedDeleteConfirm(btn: HTMLButtonElement): void {
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

// 3-button or 1-button depending on contents.
export function showFolderDeleteConfirm(btn: HTMLButtonElement): void {
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
