import { afterEach, describe, expect, it } from "vitest";

import { refresh } from "../localtime";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("localtime refresh", () => {
  it("localizes non-relative time elements once", () => {
    document.body.innerHTML = '<time datetime="2024-01-15T09:30:00Z">old</time>';

    refresh();

    const el = document.querySelector("time");
    expect(el?.textContent).toMatch(/^2024-01-15 \d{2}:30$/);
    expect(el?.dataset.localized).toBe("1");

    expect(el).not.toBeNull();
    if (!el) return;
    el.textContent = "changed";
    refresh();
    expect(el?.textContent).toBe("changed");
  });

  it("preserves a leading separator prefix", () => {
    document.body.innerHTML = '<time datetime="2024-01-15T09:30:00Z">· old</time>';

    refresh();

    expect(document.querySelector("time")?.textContent).toMatch(/^· 2024-01-15 \d{2}:30$/);
  });

  it("skips relative-time owned and invalid time elements", () => {
    document.body.innerHTML = `
      <time id="relative" data-relative datetime="2024-01-15T09:30:00Z">relative</time>
      <time id="invalid" datetime="invalid">invalid</time>
    `;

    refresh();

    expect(document.getElementById("relative")?.textContent).toBe("relative");
    expect(document.getElementById("invalid")?.textContent).toBe("invalid");
  });
});
