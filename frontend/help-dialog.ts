function getHelpDialog(): HTMLDialogElement | null {
  return document.getElementById("shortcut-help") as HTMLDialogElement | null;
}

export function isHelpOpen(): boolean {
  return getHelpDialog()?.open ?? false;
}

export function toggleHelp(): void {
  const dlg = getHelpDialog();
  if (!dlg) return;
  if (dlg.open) dlg.close();
  else dlg.showModal();
}

function bindHelp(): void {
  const dlg = getHelpDialog();
  if (!dlg) return;
  const closeBtn = dlg.querySelector<HTMLButtonElement>(".shortcut-help-close");
  if (closeBtn) closeBtn.addEventListener("click", () => dlg.close());
  dlg.addEventListener("click", (ev) => {
    if (ev.target === dlg) dlg.close();
  });
}

export function install(): void {
  document.addEventListener("DOMContentLoaded", bindHelp);
}
