// Mirrors src/rssx/domain/events.py::DomainEvent. Keep in sync.
export const DomainEvent = {
  COUNTS_CHANGED: "rssx:counts-changed",
  FEED_ADDED: "rssx:feed-added",
  FEED_FOLDER_CHANGED: "rssx:feed-folder-changed",
  FOLDER_CHANGED: "rssx:folder-changed",
} as const;

export type DomainEvent = (typeof DomainEvent)[keyof typeof DomainEvent];

export function dispatch(event: DomainEvent, target: EventTarget = document.body): void {
  target.dispatchEvent(new CustomEvent(event));
}

export function listen(
  event: DomainEvent,
  handler: (ev: Event) => void,
  target: EventTarget = document.body,
): void {
  target.addEventListener(event, handler);
}
