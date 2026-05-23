(function () {
  "use strict";

  const fmt = new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });

  function format(date) {
    const parts = Object.fromEntries(fmt.formatToParts(date).map((p) => [p.type, p.value]));
    return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}`;
  }

  function apply(root) {
    const scope = root && root.querySelectorAll ? root : document;
    const nodes = scope.querySelectorAll("time[datetime]");
    nodes.forEach((el) => {
      if (el.dataset.localized === "1") return;
      const iso = el.getAttribute("datetime");
      if (!iso) return;
      const d = new Date(iso);
      if (isNaN(d.getTime())) return;
      const prefix = el.textContent.startsWith("· ") ? "· " : "";
      el.textContent = prefix + format(d);
      el.dataset.localized = "1";
    });
  }

  document.addEventListener("DOMContentLoaded", () => apply(document));
  document.body && apply(document.body);
  document.addEventListener("htmx:afterSwap", (e) => apply(e.target));
})();
