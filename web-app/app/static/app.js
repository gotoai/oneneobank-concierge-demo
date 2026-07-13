// Mobile shell interactions.
//   * Bottom tabs switch the two directory panels (personas / campaigns).
//   * Tapping a persona opens that persona's home-screen overlay.
//   * Tapping a campaign (in a directory or a home screen) opens the campaign
//     detail overlay, stacked above.
// Injected fragments are handled via event delegation on document.
(function () {
  // --- directory tabs ---
  const tabs = document.querySelectorAll(".tabbar > .tab[data-tab]");
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
  activate(panels[(location.hash || "").replace("#", "")] ? location.hash.slice(1) : "personas");

  // --- overlays ---
  const personaOverlay = document.getElementById("persona-overlay");
  const personaContent = document.getElementById("persona-content");
  const campOverlay = document.getElementById("detail-overlay");
  const campContent = document.getElementById("detail-content");

  const open = (ov) => { ov.hidden = false; requestAnimationFrame(() => ov.classList.add("open")); };
  const close = (ov) => {
    ov.classList.remove("open");
    const done = () => { ov.hidden = true; ov.removeEventListener("transitionend", done); };
    ov.addEventListener("transitionend", done);
  };

  async function fetchInto(el, url) {
    el.innerHTML = "<p class='detail-loading'>読み込み中…</p>";
    try {
      const r = await fetch(url);
      el.innerHTML = r.ok ? await r.text() : "<p class='error'>読み込めませんでした。</p>";
    } catch { el.innerHTML = "<p class='error'>通信エラーが発生しました。</p>"; }
    el.scrollTop = 0;
  }
  async function openPersona(id) { open(personaOverlay); await fetchInto(personaContent, `/ui/persona/${encodeURIComponent(id)}/home`); }
  async function openCampaign(id) { open(campOverlay); await fetchInto(campContent, `/ui/campaign/${encodeURIComponent(id)}`); }

  function switchHome(name) {
    personaContent.querySelectorAll(".home-panel").forEach((p) => { p.hidden = p.dataset.panel !== name; });
    personaContent.querySelectorAll(".home-tab").forEach((t) => t.classList.toggle("is-active", t.dataset.homeTab === name));
    const scroller = personaContent.querySelector(".pscreen-content");
    if (scroller) scroller.scrollTop = 0;
  }

  // --- delegated clicks ---
  document.addEventListener("click", (e) => {
    const camp = e.target.closest("[data-campaign-id]");
    if (camp) { openCampaign(camp.dataset.campaignId); return; }
    const per = e.target.closest("[data-persona-id]");
    if (per) { openPersona(per.dataset.personaId); return; }
    const ht = e.target.closest("[data-home-tab]");
    if (ht) { switchHome(ht.dataset.homeTab); return; }
    if (e.target.closest("#detail-back")) { close(campOverlay); return; }
    if (e.target.closest("#persona-back")) { close(personaOverlay); return; }
  });

  // keyboard: Enter/Space on role=button cards; Esc closes the topmost overlay
  document.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-persona-id],[data-campaign-id]")) {
      e.preventDefault(); e.target.click();
    }
    if (e.key === "Escape") {
      if (!campOverlay.hidden) close(campOverlay);
      else if (!personaOverlay.hidden) close(personaOverlay);
    }
  });
})();
