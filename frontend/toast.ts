type ToastKind = "info" | "error";

function ensureHost(): HTMLElement {
  let host = document.getElementById("toast-host");
  if (!host) {
    host = document.createElement("div");
    host.id = "toast-host";
    host.className = "toast-host";
    host.setAttribute("aria-live", "polite");
    host.setAttribute("aria-atomic", "true");
    document.body.appendChild(host);
  }
  return host;
}

export function toast(message: string, kind: ToastKind = "info", durationMs = 3500): void {
  const host = ensureHost();
  const el = document.createElement("div");
  el.className = `toast toast-${kind}`;
  el.textContent = message;
  host.appendChild(el);
  // trigger transition
  requestAnimationFrame(() => el.classList.add("toast-show"));
  setTimeout(() => {
    el.classList.remove("toast-show");
    el.addEventListener("transitionend", () => el.remove(), { once: true });
    // fallback: remove after extra 500ms if no transition fires
    setTimeout(() => el.remove(), 500);
  }, durationMs);
}

export function install(): void {
  document.body.addEventListener("htmx:responseError", (ev) => {
    const detail = (ev as CustomEvent).detail as { xhr?: XMLHttpRequest } | undefined;
    const xhr = detail?.xhr;
    let msg = "保存に失敗しました";
    if (xhr) {
      const text = xhr.responseText?.trim();
      if (text && text.length < 200) msg = text;
      else if (xhr.status) msg = `${msg} (HTTP ${xhr.status})`;
    }
    toast(msg, "error");
  });
  document.body.addEventListener("htmx:sendError", () => {
    toast("通信エラーが発生しました", "error");
  });
}
