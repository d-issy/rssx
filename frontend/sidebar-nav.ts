import { currentFolderIdFromUrl } from "./folders";

type NavItem = {
  el: HTMLAnchorElement;
  scope: string;
  folder: string | null;
  feed: string | null;
};

function isHiddenByClosedDetails(el: Element): boolean {
  let node: Element | null = el;
  while (node) {
    const parent: Element | null = node.parentElement;
    if (!parent) return false;
    if (
      parent.tagName === "DETAILS" &&
      !(parent as HTMLDetailsElement).open &&
      node.tagName !== "SUMMARY"
    ) {
      return true;
    }
    node = parent;
  }
  return false;
}

function navItems(): NavItem[] {
  const sb = document.querySelector(".sidebar");
  if (!sb) return [];
  const items: NavItem[] = [];
  sb.querySelectorAll<HTMLAnchorElement>("a.sidebar-link, a.folder-link, a.feed-link").forEach(
    (a) => {
      let url: URL;
      try {
        url = new URL(a.getAttribute("href") || "", location.origin);
      } catch {
        return;
      }
      const scope = url.searchParams.get("scope");
      if (!scope) return;
      if (isHiddenByClosedDetails(a)) return;
      items.push({
        el: a,
        scope,
        folder: url.searchParams.get("folder"),
        feed: url.searchParams.get("feed"),
      });
    },
  );
  return items;
}

function currentNavIndex(items: NavItem[]): number {
  const params = new URLSearchParams(location.search);
  const scope = params.get("scope") || "all";
  const folder = params.get("folder");
  const feed = params.get("feed");
  let idx = items.findIndex((it) => {
    if (it.scope !== scope) return false;
    if (scope === "folder") return it.folder === folder;
    if (scope === "feed") return it.feed === feed;
    return true;
  });
  if (idx >= 0) return idx;
  if (scope === "feed" && feed != null) {
    const parentId = currentFolderIdFromUrl();
    if (parentId != null) {
      idx = items.findIndex((it) => it.scope === "folder" && it.folder === parentId);
    }
  }
  return idx;
}

export function navItem(delta: number): void {
  const items = navItems();
  if (!items.length) return;
  let idx = currentNavIndex(items);
  if (idx < 0) idx = delta > 0 ? 0 : items.length - 1;
  else idx = (idx + delta + items.length) % items.length;
  const href = items[idx].el.getAttribute("href");
  if (href) location.href = href;
}
