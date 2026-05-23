const fmt = new Intl.DateTimeFormat(undefined, {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

function format(date: Date): string {
  const parts = Object.fromEntries(fmt.formatToParts(date).map((p) => [p.type, p.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
}

function apply(root: ParentNode | null | undefined): void {
  const scope: ParentNode = root ?? document;
  // Skip elements owned by relative-time.ts (data-relative). Those have their
  // own formatter and would otherwise be overwritten when this listener fires
  // after htmx:afterSwap.
  const nodes = scope.querySelectorAll<HTMLTimeElement>("time[datetime]:not([data-relative])");
  nodes.forEach((el) => {
    if (el.dataset.localized === "1") return;
    const iso = el.getAttribute("datetime");
    if (!iso) return;
    const d = new Date(iso);
    if (isNaN(d.getTime())) return;
    const prefix = (el.textContent ?? "").startsWith("· ") ? "· " : "";
    el.textContent = prefix + format(d);
    el.dataset.localized = "1";
  });
}

export function refresh(root?: ParentNode | null): void {
  apply(root);
}

export function install(): void {
  document.addEventListener("DOMContentLoaded", () => apply(document));
  if (document.body) apply(document.body);
  document.addEventListener("htmx:afterSwap", (e) => {
    apply((e as Event & { target: ParentNode | null }).target);
  });
}
