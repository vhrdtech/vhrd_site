// The site's only script: the theme toggle, the code-panel tabs and the image placeholders. Everything works without
// it (the theme then follows the system, every code panel shows stacked, images show as they load).
(() => {
  const root = document.documentElement;
  const dark = matchMedia("(prefers-color-scheme: dark)");
  const current = () => root.dataset.theme || (dark.matches ? "dark" : "light");

  const toggle = document.querySelector(".theme-toggle");
  const label = () => {
    const next = current() === "dark" ? "light" : "dark";
    toggle.setAttribute("aria-label", `Switch to ${next} theme`);
    toggle.title = `Switch to ${next} theme`;
  };
  if (toggle) {
    label();
    dark.addEventListener("change", label);
    toggle.addEventListener("click", () => {
      const next = current() === "dark" ? "light" : "dark";
      // Back to the system's choice when it matches, so a later change of the system setting is followed again.
      if (next === (dark.matches ? "dark" : "light")) {
        delete root.dataset.theme;
        try { localStorage.removeItem("theme"); } catch (e) {}
      } else {
        root.dataset.theme = next;
        try { localStorage.setItem("theme", next); } catch (e) {}
      }
      label();
    });
  }

  // Tabs per the WAI-ARIA pattern: click or arrow keys select, Home/End jump, only the selected tab is in the tab order.
  for (const box of document.querySelectorAll("[data-tabs]")) {
    const tabs = [...box.querySelectorAll('[role="tab"]')];
    const panels = tabs.map((t) => document.getElementById(t.getAttribute("aria-controls")));
    const select = (i, focus) => {
      tabs.forEach((t, j) => {
        t.setAttribute("aria-selected", String(i === j));
        t.tabIndex = i === j ? 0 : -1;
        panels[j].hidden = i !== j;
      });
      if (focus) tabs[i].focus();
    };
    tabs.forEach((t, i) => {
      t.addEventListener("click", () => select(i, false));
      t.addEventListener("keydown", (e) => {
        const n = tabs.length;
        const to = { ArrowRight: (i + 1) % n, ArrowLeft: (i - 1 + n) % n, Home: 0, End: n - 1 }[e.key];
        if (to !== undefined) { e.preventDefault(); select(to, true); }
      });
    });
    panels.forEach((p) => p.setAttribute("tabindex", "0"));
    box.querySelector('[role="tablist"]').hidden = false;
    box.classList.add("js-tabs");
    select(0, false);
  }

  // Pictures still on their way show as a small scope screen until they arrive, then fade in over it (site.css
  // "Image placeholders"). One that has already arrived is left alone, and so is the eager hero: hidden while it
  // loads, its largest paint would wait for the fade.
  for (const img of document.querySelectorAll(".fig-frame img")) {
    if (img.complete || img.loading === "eager") continue;
    const frame = img.closest(".fig-frame");
    frame.classList.add("img-wait");
    const show = () => {
      frame.classList.replace("img-wait", "img-in");
      // Once faded in, the screen goes for good (its sweep stops with it).
      frame.addEventListener("transitionend", () => frame.classList.remove("img-in"), { once: true });
    };
    img.addEventListener("load", show, { once: true });
    img.addEventListener("error", show, { once: true });
  }
})();
