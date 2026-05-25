import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { refresh } from "../lib/relative-time";

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2024, 0, 15, 12, 0));
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("relative-time refresh", () => {
  it("formats today's time as HH:mm", () => {
    document.body.innerHTML = '<time data-relative datetime="2024-01-15T09:30:00">old</time>';

    refresh();

    const el = document.querySelector("time");
    expect(el?.textContent).toBe("09:30");
    expect(el?.title).toBe("2024-01-15 09:30");
  });

  it("formats yesterday and tomorrow with labels", () => {
    document.body.innerHTML = `
      <time id="y" data-relative datetime="2024-01-14T23:00:00">old</time>
      <time id="t" data-relative datetime="2024-01-16T01:00:00">old</time>
    `;

    refresh();

    expect(document.getElementById("y")?.textContent).toBe("昨日 23:00");
    expect(document.getElementById("t")?.textContent).toBe("明日 01:00");
  });

  it("leaves invalid datetimes unchanged", () => {
    document.body.innerHTML = '<time data-relative datetime="invalid">old</time>';

    refresh();

    expect(document.querySelector("time")?.textContent).toBe("old");
  });
});
