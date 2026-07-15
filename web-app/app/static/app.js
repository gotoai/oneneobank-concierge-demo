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
  const conciergeOverlay = document.getElementById("concierge-overlay");
  const conciergeContent = document.getElementById("concierge-content");
  const entryOverlay = document.getElementById("entry-overlay");
  const entryContent = document.getElementById("entry-content");

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
  // The persona whose home screen is open = the customer the concierge speaks to.
  let currentPersonaId = null;
  // Concierge conversation so far (oldest first); reset each time the pane opens.
  let conciergeHistory = [];

  async function openPersona(id) { currentPersonaId = id; open(personaOverlay); await fetchInto(personaContent, `/ui/persona/${encodeURIComponent(id)}/home`); }
  async function openCampaign(id) { open(campOverlay); await fetchInto(campContent, `/ui/campaign/${encodeURIComponent(id)}`); }
  async function openConcierge(id) {
    conciergeHistory = [];
    open(conciergeOverlay);
    const q = currentPersonaId ? `?persona_id=${encodeURIComponent(currentPersonaId)}` : "";
    await fetchInto(conciergeContent, `/ui/campaign/${encodeURIComponent(id)}/concierge${q}`);
  }
  async function openEntry(id) {
    open(entryOverlay);
    await fetchInto(entryContent, `/ui/campaign/${encodeURIComponent(id)}/entry`);
    // Localise the browser's native "required checkbox" validation message to Japanese.
    const agree = entryContent.querySelector('#entry-form input[name="agree"]');
    if (agree) {
      const msg = "続行するには、このチェックボックスをオンにしてください。";
      agree.addEventListener("invalid", () => agree.setCustomValidity(msg));
      agree.addEventListener("change", () => agree.setCustomValidity(""));
    }
  }

  function switchHome(name) {
    personaContent.querySelectorAll(".home-panel").forEach((p) => { p.hidden = p.dataset.panel !== name; });
    personaContent.querySelectorAll(".home-tab").forEach((t) => t.classList.toggle("is-active", t.dataset.homeTab === name));
    const scroller = personaContent.querySelector(".pscreen-content");
    if (scroller) scroller.scrollTop = 0;
  }

  // --- delegated clicks ---
  document.addEventListener("click", (e) => {
    const entry = e.target.closest("[data-entry-id]");
    if (entry) { openEntry(entry.dataset.entryId); return; }
    const camp = e.target.closest("[data-campaign-id]");
    if (camp) {
      // From a customer (persona) screen -> concierge split view; from the
      // directory tab -> plain detail.
      if (camp.closest("#persona-overlay")) openConcierge(camp.dataset.campaignId);
      else openCampaign(camp.dataset.campaignId);
      return;
    }
    const per = e.target.closest("[data-persona-id]");
    if (per) { openPersona(per.dataset.personaId); return; }
    const ht = e.target.closest("[data-home-tab]");
    if (ht) { switchHome(ht.dataset.homeTab); return; }
    if (e.target.closest("#detail-back")) { close(campOverlay); return; }
    if (e.target.closest("#concierge-back")) { close(conciergeOverlay); return; }
    if (e.target.closest("#entry-back, .entry-close")) { close(entryOverlay); return; }
    if (e.target.closest("#persona-back")) { close(personaOverlay); return; }
  });

  // Forms — concierge chat and campaign entry (both UI-only for now).
  document.addEventListener("submit", (e) => {
    if (e.target.id === "c-chat-form") submitChat(e);
    else if (e.target.id === "entry-form") submitEntry(e);
  });

  // Render the concierge's Markdown reply to safe HTML. HTML is escaped FIRST, so
  // model output can never inject markup — we only ever add our own controlled tags
  // (strong / em / code / ul / li / p / br). Supports the subset the agent emits:
  // **bold**, *italic*, `code`, and `*`/`-` bullet lists.
  function escapeHtml(s) {
    return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }
  function renderInline(s) {          // s is already HTML-escaped
    return s
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")   // bold before italic
      .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  }
  function renderMarkdown(text) {
    const lines = escapeHtml(text).split(/\r?\n/);
    const out = [];
    let inList = false, para = [];
    const flushPara = () => { if (para.length) { out.push("<p>" + para.join("<br>") + "</p>"); para = []; } };
    const closeList = () => { if (inList) { out.push("</ul>"); inList = false; } };
    for (const raw of lines) {
      const line = raw.replace(/\s+$/, "");
      const bullet = line.match(/^\s*[*-]\s+(.*)$/);
      if (bullet) {
        flushPara();
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push("<li>" + renderInline(bullet[1]) + "</li>");
      } else if (line.trim() === "") {
        flushPara(); closeList();
      } else {
        closeList();
        para.push(renderInline(line));
      }
    }
    flushPara(); closeList();
    return out.join("");
  }

  // Parse one SSE frame ("event: x\ndata: {...}") into { event, data }.
  function parseSse(raw) {
    let event = "message";
    const dataLines = [];
    for (const line of raw.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
    }
    let data = {};
    const joined = dataLines.join("\n");
    if (joined) { try { data = JSON.parse(joined); } catch { /* keep {} */ } }
    return { event, data };
  }

  // Send a chat turn to the proxy and stream the concierge reply into a bubble.
  async function submitChat(e) {
    e.preventDefault();
    const form = e.target;
    const chat = form.closest(".c-chat");
    const input = form.querySelector("#c-chat-text");
    const sendBtn = form.querySelector("button[type=submit]");
    const text = (input.value || "").trim();
    if (!text) return;
    const campaignId = chat ? chat.dataset.chatCampaign : "";
    const personaId = chat ? chat.dataset.chatPersona : "";
    const langSel = chat ? chat.querySelector("#c-chat-lang") : null;
    const language = langSel ? langSel.value : "ja";
    const log = document.getElementById("c-chat-log");

    const user = document.createElement("div");
    user.className = "msg user";
    user.textContent = text;             // textContent avoids HTML injection
    log.appendChild(user);

    const bot = document.createElement("div");
    bot.className = "msg assistant";
    bot.textContent = "…";               // typing placeholder, replaced by the first delta
    log.appendChild(bot);
    input.value = "";
    log.scrollTop = log.scrollHeight;
    input.disabled = true; if (sendBtn) sendBtn.disabled = true;

    let answer = "";
    try {
      const r = await fetch(`/ui/campaign/${encodeURIComponent(campaignId)}/concierge/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ persona_id: personaId, message: text, history: conciergeHistory, language }),
      });
      if (!r.ok || !r.body) throw new Error("bad response " + r.status);

      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      let errMsg = null;
      let done = false;
      while (!done) {
        const { value, done: streamDone } = await reader.read();
        if (streamDone) break;
        buf += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const { event, data } = parseSse(buf.slice(0, idx));
          buf = buf.slice(idx + 2);
          if (event === "error") { errMsg = data.error || "エラーが発生しました。"; done = true; break; }
          else if (event === "done") { done = true; break; }
          else if (typeof data.delta === "string") {
            answer += data.delta;
            bot.innerHTML = renderMarkdown(answer);   // safe: content is escaped first
            log.scrollTop = log.scrollHeight;
          }
        }
      }
      if (errMsg) {
        bot.classList.add("muted");
        bot.textContent = "申し訳ございません。ただ今ご案内できません。（" + errMsg + "）";
        answer = "";
      }
    } catch (err) {
      bot.classList.add("muted");
      bot.textContent = "通信エラーが発生しました。時間をおいて再度お試しください。";
      answer = "";
    } finally {
      input.disabled = false; if (sendBtn) sendBtn.disabled = false;
      input.focus();
    }

    if (answer) {
      conciergeHistory.push({ role: "user", text });
      conciergeHistory.push({ role: "assistant", text: answer });
    }
    log.scrollTop = log.scrollHeight;
  }

  // Entry form — replace it with a success confirmation (UI-only; nothing persists).
  function submitEntry(e) {
    e.preventDefault();
    const form = e.target;
    const done = document.createElement("div");
    done.className = "entry-done";
    const icon = document.createElement("div");
    icon.className = "entry-done-icon"; icon.textContent = "✅";
    const title = document.createElement("div");
    title.className = "entry-done-title"; title.textContent = "エントリーを受け付けました";
    const sub = document.createElement("div");
    sub.className = "entry-done-sub"; sub.textContent = "「" + (form.dataset.title || "") + "」";
    const note = document.createElement("div");
    note.className = "entry-done-note";
    note.textContent = "条件の達成状況は、達成後にコンシェルジュや利用明細でご確認いただけます。";
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "entry-close"; btn.textContent = "閉じる";
    done.append(icon, title, sub, note, btn);
    form.replaceWith(done);
  }

  // keyboard: Enter/Space on role=button cards; Esc closes the topmost overlay
  document.addEventListener("keydown", (e) => {
    if ((e.key === "Enter" || e.key === " ") && e.target.matches("[data-persona-id],[data-campaign-id]")) {
      e.preventDefault(); e.target.click();
    }
    if (e.key === "Escape") {
      if (!entryOverlay.hidden) close(entryOverlay);
      else if (!campOverlay.hidden) close(campOverlay);
      else if (!conciergeOverlay.hidden) close(conciergeOverlay);
      else if (!personaOverlay.hidden) close(personaOverlay);
    }
  });
})();
