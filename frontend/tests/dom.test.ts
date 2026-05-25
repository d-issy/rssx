import { afterEach, describe, expect, it, vi } from "vitest";

import { DomainEvent, dispatch, listen } from "../lib/events";
import { isTyping, parseFragment } from "../lib/dom";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("isTyping", () => {
  it("returns true when an input is focused", () => {
    document.body.innerHTML = '<input id="q">';
    document.getElementById("q")?.focus();

    expect(isTyping()).toBe(true);
  });

  it("returns false when a normal element is focused", () => {
    document.body.innerHTML = '<button id="b">button</button>';
    document.getElementById("b")?.focus();

    expect(isTyping()).toBe(false);
  });
});

describe("parseFragment", () => {
  it("returns the first element from an html fragment", () => {
    const el = parseFragment<HTMLAnchorElement>('<a href="/manage">管理</a>');

    expect(el?.tagName).toBe("A");
    expect(el?.getAttribute("href")).toBe("/manage");
    expect(el?.textContent).toBe("管理");
  });
});

describe("events", () => {
  it("dispatch fires the named DomainEvent on body", () => {
    const handler = vi.fn();
    listen(DomainEvent.COUNTS_CHANGED, handler);

    dispatch(DomainEvent.COUNTS_CHANGED);

    expect(handler).toHaveBeenCalledOnce();
  });
});
