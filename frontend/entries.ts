import { dispatchCountsChanged, parseFragment } from "./dom";

const READ_DELAY_MS = 2000;

let selectedIndex = -1;
let autoReadTimer: ReturnType<typeof setTimeout> | null = null;

function getEntries(): HTMLElement[] {
  return Array.from(document.querySelectorAll<HTMLElement>("#entries .entry"));
}

function clearAutoRead(): void {
  if (autoReadTimer) {
    clearTimeout(autoReadTimer);
    autoReadTimer = null;
  }
}

function collapse(entryEl: HTMLElement): void {
  const body = entryEl.querySelector<HTMLElement>(".entry-body");
  if (!body || body.hidden) return;
  body.hidden = true;
  entryEl.classList.remove("expanded");
}

function replaceEntry(entryEl: HTMLElement, html: string): void {
  const next = parseFragment<HTMLElement>(html);
  if (!next) return;
  const oldBody = entryEl.querySelector<HTMLElement>(".entry-body");
  const newBody = next.querySelector<HTMLElement>(".entry-body");
  if (oldBody && newBody && !oldBody.hidden) {
    newBody.innerHTML = oldBody.innerHTML;
    newBody.hidden = false;
    next.classList.add("expanded");
  }
  if (entryEl.classList.contains("selected")) next.classList.add("selected");
  entryEl.replaceWith(next);
}

async function markRead(entryEl: HTMLElement, value: boolean): Promise<void> {
  const id = entryEl.dataset.entryId;
  if (!id) return;
  const res = await fetch(`/entries/${id}/read?value=${value ? 1 : 0}`, { method: "POST" });
  const html = await res.text();
  replaceEntry(entryEl, html);
  dispatchCountsChanged();
}

async function loadEntryBody(body: HTMLElement, id: string): Promise<void> {
  const res = await fetch(`/entries/${id}`);
  body.innerHTML = await res.text();
}

function select(index: number, opts: { expand?: boolean } = {}): void {
  const list = getEntries();
  if (list.length === 0) return;
  const clamped = Math.max(0, Math.min(list.length - 1, index));
  list.forEach((el, i) => el.classList.toggle("selected", i === clamped));
  selectedIndex = clamped;
  const el = list[clamped];
  el.scrollIntoView({ block: "nearest", behavior: "smooth" });
  if (opts.expand) {
    clearAutoRead();
    list.forEach((other, i) => {
      if (i !== clamped) collapse(other);
    });
    if (!el.classList.contains("expanded")) {
      toggleExpand(el);
    }
  }
}

export function toggleExpand(entryEl: HTMLElement): void {
  const body = entryEl.querySelector<HTMLElement>(".entry-body");
  if (!body) return;
  clearAutoRead();
  if (body.hidden) {
    const id = entryEl.dataset.entryId;
    if (id && !body.innerHTML.trim()) {
      body.innerHTML = "<p>読み込み中…</p>";
      void loadEntryBody(body, id);
    }
    body.hidden = false;
    entryEl.classList.add("expanded");
    if (!entryEl.classList.contains("read")) {
      autoReadTimer = setTimeout(() => void markRead(entryEl, true), READ_DELAY_MS);
    }
  } else {
    body.hidden = true;
    entryEl.classList.remove("expanded");
  }
}

export function toggleRead(entryEl: HTMLElement): void {
  void markRead(entryEl, !entryEl.classList.contains("read"));
}

export async function toggleStar(entryEl: HTMLElement): Promise<void> {
  const id = entryEl.dataset.entryId;
  if (!id) return;
  const res = await fetch(`/entries/${id}/star`, { method: "POST" });
  const html = await res.text();
  replaceEntry(entryEl, html);
  dispatchCountsChanged();
}

export function openOriginal(entryEl: HTMLElement): void {
  const url = entryEl.dataset.url;
  if (url) window.open(url, "_blank", "noopener,noreferrer");
}

export function getSelected(): HTMLElement | null {
  const list = getEntries();
  return selectedIndex >= 0 ? (list[selectedIndex] ?? null) : null;
}

export function selectRelative(delta: number, opts: { expand?: boolean } = {}): void {
  select(selectedIndex < 0 ? 0 : selectedIndex + delta, opts);
}

export function selectFirst(): void {
  select(0, { expand: false });
}

export function selectLast(): void {
  select(getEntries().length - 1, { expand: false });
}

export function install(): void {
  document.addEventListener("click", (ev) => {
    const target = ev.target as Element | null;
    const row = target?.closest(".entry-row");
    if (!row || target?.closest(".star")) return;
    const entryEl = row.parentElement as HTMLElement | null;
    if (!entryEl) return;
    const list = getEntries();
    selectedIndex = list.indexOf(entryEl);
    list.forEach((el, i) => {
      el.classList.toggle("selected", i === selectedIndex);
      if (i !== selectedIndex) collapse(el);
    });
    toggleExpand(entryEl);
  });
}
