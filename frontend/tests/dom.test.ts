import { afterEach, describe, expect, it, vi } from "vitest";

import { COUNTS_CHANGED_EVENT, dispatchCountsChanged, isTyping, parseFragment } from "../dom";

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

describe("dispatchCountsChanged", () => {
  it("dispatches the counts changed event on body", () => {
    const listener = vi.fn();
    document.body.addEventListener(COUNTS_CHANGED_EVENT, listener);

    dispatchCountsChanged();

    expect(listener).toHaveBeenCalledOnce();
  });
});
