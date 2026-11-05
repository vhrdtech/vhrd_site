// The site's only script: the theme toggle, the code-panel tabs, the image placeholders and the signup form. Everything
// works without it (the theme is then dark, every code panel shows stacked, images show as they load, the form posts
// and the service sends the visitor back with a message).
(() => {
  const root = document.documentElement;
  // Dark is the default (base.html sets it); light is the visitor's choice, remembered.
  const current = () => root.dataset.theme || "dark";

  const toggle = document.querySelector(".theme-toggle");
  const label = () => {
    const next = current() === "dark" ? "light" : "dark";
    toggle.setAttribute("aria-label", `Switch to ${next} theme`);
    toggle.title = `Switch to ${next} theme`;
  };
  if (toggle) {
    label();
    toggle.addEventListener("click", () => {
      const next = current() === "dark" ? "light" : "dark";
      root.dataset.theme = next;
      // Back to dark clears the choice: dark is the default.
      try { next === "light" ? localStorage.setItem("theme", "light") : localStorage.removeItem("theme"); } catch (e) {}
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

  // The signup form (vh.notify): posted with fetch, the answer shown in place as the message the service would send a
  // form without script back to. The status names it; nothing of the answer's text is shown.
  for (const form of document.querySelectorAll("form[data-notify]")) {
    const button = form.querySelector("button[type=submit]");
    const show = (name) => {
      // a message left in the address by an earlier post without script would show beside this one
      if (location.hash.startsWith("#notify-")) history.replaceState(null, "", location.pathname + location.search);
      form.classList.add("js-sent");
      for (const m of form.querySelectorAll(".notify-msg")) m.classList.toggle("is-shown", m.id === `notify-${name}`);
      document.getElementById(`notify-${name}`).focus();
    };
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      button.disabled = true;
      let name = "err";
      try {
        const r = await fetch(form.action, {
          method: "POST",
          body: new URLSearchParams(new FormData(form)),
          headers: { Accept: "application/json" },
        });
        name = { 200: "ok", 400: "bad", 429: "wait" }[r.status] || "err";
      } catch (err) {}
      button.disabled = false;
      if (name === "ok") form.reset();
      show(name);
    });
  }
})();
