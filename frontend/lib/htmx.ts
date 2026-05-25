// Ambient binding for the global `htmx` provided by the htmx.org script tag.
// Mirrors the helper-style API of src/rssx/lib/htmx.py on the client side.

export interface Htmx {
  ajax: (method: string, url: string, opts: Record<string, unknown>) => Promise<void>;
  process: (root: Element | Document) => void;
  trigger: (target: Element, name: string) => void;
}

declare global {
  // eslint-disable-next-line no-var
  var htmx: Htmx;
}

export function ajax(method: string, url: string, opts: Record<string, unknown>): Promise<void> {
  return htmx.ajax(method, url, opts);
}

export function process(root: Element | Document): void {
  htmx.process(root);
}

export function trigger(target: Element, name: string): void {
  htmx.trigger(target, name);
}
