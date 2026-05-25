function pad2(n: number): string {
  return n.toString().padStart(2, "0");
}

function formatTime(d: Date): string {
  return `${pad2(d.getHours())}:${pad2(d.getMinutes())}`;
}

function formatAbsolute(d: Date): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())} ${formatTime(d)}`;
}

function startOfDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function formatNice(d: Date, now: Date): string {
  const time = formatTime(d);
  const dayDiff = Math.round((startOfDay(d) - startOfDay(now)) / 86_400_000);
  if (dayDiff === 0) return time;
  if (dayDiff === 1) return `明日 ${time}`;
  if (dayDiff === -1) return `昨日 ${time}`;
  return formatAbsolute(d);
}

function apply(root: ParentNode | null | undefined): void {
  const scope: ParentNode = root ?? document;
  const now = new Date();
  scope.querySelectorAll<HTMLTimeElement>("time[data-relative][datetime]").forEach((el) => {
    const iso = el.getAttribute("datetime");
    if (!iso) return;
    const d = new Date(iso);
    if (isNaN(d.getTime())) return;
    el.textContent = formatNice(d, now);
    el.title = formatAbsolute(d);
  });
}

export function refresh(root?: ParentNode | null): void {
  apply(root);
}

export function install(): void {
  document.addEventListener("DOMContentLoaded", () => apply(document));
  if (document.body) apply(document.body);
  document.body.addEventListener("htmx:afterSwap", (e) => {
    apply((e as Event & { target: ParentNode | null }).target);
  });
  // Re-evaluate periodically so "今日 → 明日" rollovers update without manual reload.
  setInterval(() => apply(document), 60 * 1000);
}
