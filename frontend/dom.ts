export function isTyping(): boolean {
  const el = document.activeElement as HTMLElement | null;
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
}

export function parseFragment<T extends Element = HTMLElement>(html: string): T | null {
  const tmp = document.createElement("template");
  tmp.innerHTML = html.trim();
  return tmp.content.firstElementChild as T | null;
}

export const COUNTS_CHANGED_EVENT = "rssx:counts-changed";

export function dispatchCountsChanged(): void {
  document.body.dispatchEvent(new CustomEvent(COUNTS_CHANGED_EVENT));
}
