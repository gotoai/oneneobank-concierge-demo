// Bottom-tab switching for the mobile shell. Server renders both panels; we just
// toggle which one is visible. Deep-link via #campaigns / #personas is supported.
(function () {
  const tabs = document.querySelectorAll(".tab");
  const panels = {
    personas: document.getElementById("panel-personas"),
    campaigns: document.getElementById("panel-campaigns"),
  };

  function activate(name) {
    if (!panels[name]) return;
    for (const [key, panel] of Object.entries(panels)) {
      panel.hidden = key !== name;
      panel.classList.toggle("is-active", key === name);
    }
    tabs.forEach((t) => {
      const on = t.dataset.tab === name;
      t.classList.toggle("is-active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    if (location.hash !== "#" + name) history.replaceState(null, "", "#" + name);
  }

  tabs.forEach((t) => t.addEventListener("click", () => activate(t.dataset.tab)));

  const initial = (location.hash || "").replace("#", "");
  activate(panels[initial] ? initial : "personas");
})();
