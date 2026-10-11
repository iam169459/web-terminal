/* Self-update view: check upstream, install updates, watch the log across restart. */
const Updater = (() => {
  let loaded = false;
  let pollTimer = null;
  let restarting = false;
  let lastInfo = null;

  function init() {
    if (loaded) return;
    loaded = true;
    UI.$("#update-btn").addEventListener("click", open);
    UI.$("#ver-pill").addEventListener("click", open);
    UI.$("#up-check").addEventListener("click", () => check(true));
    UI.$("#up-run").addEventListener("click", run);
    UI.$("#up-clear-log").addEventListener("click", clearLog);
  }

  async function open() {
    init();
    UI.openModal("update-modal");
    await load(false);
  }

  /** Lightweight fetch used on app boot just to fill the sidebar badge. */
  async function refreshBadge() {
    init();
    try {
      const data = await API.get("/api/update/status");
      renderBadge(data.info);
    } catch (err) { /* badge is decorative */ }
  }

  function renderBadge(info) {
    const pill = UI.$("#ver-pill");
    if (!info || !info.available) {
      pill.textContent = "not a git checkout";
      pill.className = "pill";
      return;
    }
    pill.textContent = info.sha || "?";
    pill.className = "pill " + (info.update_available ? "pill-warn" : "pill-ok");
    pill.title = info.update_available
      ? `${info.behind} commit(s) behind - click to update`
      : `Up to date (${info.sha}) - click for details`;
  }

  function stateOf(info, running) {
    if (running) return { cls: "pill pill-warn", text: "updating…" };
    if (!info.available) return { cls: "pill", text: "no git" };
    if (info.fetch_error) return { cls: "pill pill-danger", text: "fetch failed" };
    if (info.error) return { cls: "pill pill-warn", text: "no upstream" };
    if (info.update_available) return { cls: "pill pill-warn", text: `${info.behind} behind` };
    return { cls: "pill pill-ok", text: "up to date" };
  }

  function setState(cls, text) {
    const pill = UI.$("#up-state");
    pill.className = cls;
    pill.textContent = text;
  }

  function fmtDate(value) {
    if (!value) return "—";
    const d = new Date(value);
    return isNaN(d) ? value : UI.fmtDate(d.getTime());
  }

  function render(data) {
    const info = data.info || {};
    lastInfo = info;
    renderBadge(info);

    const state = stateOf(info, data.running);
    setState(state.cls, state.text);

    const rows = [];
    const add = (k, v) => rows.push(`<dt>${UI.esc(k)}</dt><dd>${v}</dd>`);
    if (info.available) {
      add("Installed", `${UI.esc(info.sha)} · ${UI.esc(info.message)}`);
      add("Branch", UI.esc(info.branch));
      add("Last commit", `${UI.esc(fmtDate(info.date))}${info.author ? " · " + UI.esc(info.author) : ""}`);
      add("Upstream", info.remote_url ? UI.esc(info.remote_url) : "—");
      add("Status", info.update_available
        ? `<span style="color:var(--warn)">${info.behind} commit(s) behind</span>`
        : `<span style="color:var(--ok)">up to date</span>`);
      if (info.ahead) add("Local commits", `<span style="color:var(--warn)">${info.ahead} ahead of upstream</span>`);
      if (info.dirty) add("Working tree", `<span style="color:var(--warn)">modified - these changes will be discarded</span>`);
      if (info.incoming && info.incoming.length) {
        add("Latest upstream", `${UI.esc(info.latest_sha)} · ${UI.esc(info.latest_message)}`);
      }
      add("Install path", UI.esc(info.path));
      add("Restart mode", UI.esc(data.restart_mode || "manual"));
    } else {
      add("Available", "No - this install is not a git checkout");
      add("Reason", UI.esc(info.git_installed ? "no .git directory found" : "git is not installed"));
      add("Install path", UI.esc(info.path));
    }
    UI.$("#up-info").innerHTML = rows.join("");

    // Incoming commits
    const wrap = UI.$("#up-incoming-wrap");
    if (info.incoming && info.incoming.length) {
      wrap.classList.remove("hidden");
      UI.$("#up-incoming").innerHTML = info.incoming.map((c) =>
        `<div class="list-row"><div class="row-top">
           <span class="name">${UI.esc(c.message)}</span>
           <span class="sub">${UI.esc(c.author)} · ${UI.esc(fmtDate(c.date))}</span>
           <span class="val">${UI.esc(c.sha)}</span>
         </div></div>`
      ).join("");
    } else {
      wrap.classList.add("hidden");
    }

    // Buttons
    const runBtn = UI.$("#up-run");
    const canUpdate = info.available && !data.running && (info.update_available || info.dirty);
    runBtn.disabled = !canUpdate || data.running;
    runBtn.textContent = data.running ? "Updating…" : "Update now";
    UI.$("#up-check").disabled = data.running || !info.available;

    if (data.log) {
      UI.$("#up-log").textContent = data.log;
      const log = UI.$("#up-log");
      log.scrollTop = log.scrollHeight;
    }
  }

  async function load(fetchNow) {
    try {
      const data = await API.get(fetchNow ? "/api/update/check" : "/api/update/status", undefined);
      render(data);
      return data;
    } catch (err) {
      UI.toast(err.message, "err");
      return null;
    }
  }

  async function check(showToast) {
    const btn = UI.$("#up-check");
    btn.disabled = true;
    btn.textContent = "Checking…";
    try {
      const data = await API.post("/api/update/check", {});
      render(data);
      if (showToast) {
        UI.toast(data.info.update_available
          ? `${data.info.behind} commit(s) available`
          : "Already up to date", data.info.update_available ? "info" : "ok");
      }
    } catch (err) {
      UI.toast(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "Check again";
    }
  }

  async function run() {
    const info = lastInfo || {};
    const ok = await UI.confirmDialog({
      title: "Update Server Console?",
      message: `This pulls the latest code from ${info.remote_url || "origin"} and restarts the server.`,
      sub: (info.dirty ? "Your local modifications WILL be discarded. " : "") +
           (info.update_available ? `${info.behind} commit(s) will be installed. ` : "") +
           "The web UI will be unavailable for a few seconds.",
      okText: "Update now",
      danger: info.dirty,
    });
    if (!ok) return;

    try {
      await API.post("/api/update/run", {});
    } catch (err) {
      UI.toast(err.message, "err");
      return;
    }
    restarting = true;
    UI.toast("Update started - the server will restart shortly", "info");
    startPolling();
  }

  function startPolling() {
    clearInterval(pollTimer);
    pollTimer = setInterval(tick, 2000);
    tick();
  }

  async function tick() {
    let data;
    try {
      data = await API.get("/api/update/status");
    } catch (err) {
      // Server is down for the restart - keep waiting for it to come back.
      setState("pill pill-warn", "restarting…");
      UI.$("#up-run").disabled = true;
      return;
    }
    if (data) render(data);

    if (restarting && data && !data.running) {
      // Server is back with the new code: reload so the browser picks it up.
      restarting = false;
      clearInterval(pollTimer);
      UI.toast("Update complete - reloading", "ok");
      setTimeout(() => location.reload(), 1800);
    }
  }

  async function clearLog() {
    try {
      await API.post("/api/update/clear-log", {});
      UI.$("#up-log").textContent = "Log cleared.";
    } catch (err) {
      UI.toast(err.message, "err");
    }
  }

  return { init, open, refreshBadge };
})();
