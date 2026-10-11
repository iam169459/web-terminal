/* systemd service manager view. */
const Services = (() => {
  let loaded = false;
  let units = [];
  let filter = "";
  let sudoOk = false;
  let busy = new Set();

  function init() {
    if (loaded) return;
    loaded = true;
    UI.$("#s-refresh").addEventListener("click", () => refresh(true));
    let debounce = null;
    UI.$("#s-search").addEventListener("input", (e) => {
      clearTimeout(debounce);
      debounce = setTimeout(() => { filter = e.target.value.trim().toLowerCase(); render(); }, 200);
    });
  }

  async function refresh(showErrors) {
    try {
      const data = await API.get("/api/services");
      if (!data.available) {
        UI.$("#s-body").innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--faint);padding:26px">systemctl is not available on this host</td></tr>`;
        return;
      }
      units = data.services || [];
      sudoOk = Boolean(data.sudo);
      UI.$("#s-count").textContent = `${data.total} units`;
      UI.$("#s-running").textContent = `${data.running} running`;
      UI.$("#s-failed").textContent = `${data.failed} failed`;

      const note = UI.$("#s-sudo-note");
      if (!data.sudo && data.total > 0) {
        note.classList.remove("hidden");
        note.textContent =
          "Running without elevated privileges - you can view services and logs, but start/stop/restart will fail. " +
          "Run the server as root or grant passwordless sudo to enable control.";
      } else {
        note.classList.add("hidden");
      }
      render();
    } catch (err) {
      if (showErrors) UI.toast(err.message, "err");
    }
  }

  function statePill(active) {
    const map = {
      active: "pill-ok", failed: "pill-danger", inactive: "",
      activating: "pill-warn", deactivating: "pill-warn", reloading: "pill-warn",
    };
    return `<span class="pill ${map[active] || ""}">${UI.esc(active)}</span>`;
  }

  function enabledPill(state) {
    if (!state) return `<span class="pill">—</span>`;
    if (state === "enabled") return `<span class="pill pill-ok">enabled</span>`;
    if (state === "disabled") return `<span class="pill">disabled</span>`;
    return `<span class="pill pill-warn">${UI.esc(state)}</span>`;
  }

  function render() {
    const body = UI.$("#s-body");
    const rows = units.filter((s) =>
      !filter || s.unit.toLowerCase().includes(filter) || (s.description || "").toLowerCase().includes(filter)
    );

    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--faint);padding:26px">No matching units</td></tr>`;
      return;
    }

    body.innerHTML = rows.slice(0, 600).map((s) => {
      const isActive = s.active === "active";
      const enabled = s.enabled === "enabled";
      return `<tr data-unit="${UI.esc(s.unit)}">
          <td class="name-cell">${UI.esc(s.unit)}</td>
          <td>${statePill(s.active)} <span class="pill">${UI.esc(s.sub)}</span></td>
          <td>${UI.esc(s.load)}</td>
          <td>${enabledPill(s.enabled)}</td>
          <td class="cmd" title="${UI.esc(s.description)}">${UI.esc(s.description || "—")}</td>
          <td class="actions-col"><div class="row-actions">
            ${isActive
              ? `<button class="btn btn-sm" data-act="stop" ${sudoOk ? "" : "disabled"}>Stop</button>
                 <button class="btn btn-sm" data-act="restart" ${sudoOk ? "" : "disabled"}>Restart</button>`
              : `<button class="btn btn-sm btn-primary" data-act="start" ${sudoOk ? "" : "disabled"}>Start</button>`}
            <button class="btn btn-sm" data-act="${enabled ? "disable" : "enable"}" ${sudoOk ? "" : "disabled"}>${enabled ? "Disable" : "Enable"}</button>
            <button class="btn btn-sm" data-act="logs">Logs</button>
          </div></td>
        </tr>`;
    }).join("");

    body.querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const unit = btn.closest("tr").dataset.unit;
        const act = btn.dataset.act;
        if (act === "logs") return showLogs(unit);

        if (["stop", "restart", "disable", "mask"].includes(act)) {
          const ok = await UI.confirmDialog({
            title: `${act[0].toUpperCase() + act.slice(1)} ${unit}?`,
            message: `About to run: systemctl ${act} ${unit}`,
            sub: act === "stop" ? "Services that depend on this unit may also stop." : "",
            okText: act[0].toUpperCase() + act.slice(1),
            danger: act === "stop",
          });
          if (!ok) return;
        }

        const key = `${unit}:${act}`;
        busy.add(key);
        render();
        try {
          const res = await API.post(`/api/services/${encodeURIComponent(unit)}/action`, { action: act });
          if (res.ok) UI.toast(`${unit}: ${act} succeeded (now ${res.state})`, "ok");
          else UI.toast(`${unit}: ${act} failed - ${res.message || "unknown error"}`, "err");
        } catch (err) {
          UI.toast(`${unit}: ${err.message}`, "err");
        } finally {
          busy.delete(key);
          refresh(false);
        }
      });
    });
  }

  async function showLogs(unit) {
    UI.showPanel(`${unit} - journal`, `<div class="log-output">Loading journal…</div>`);
    try {
      const data = await API.get(`/api/services/${encodeURIComponent(unit)}/logs`, { lines: 250 });
      const body = UI.$("#gm-body .log-output");
      body.textContent = data.output || "(no output)";
      body.scrollTop = body.scrollHeight;
    } catch (err) {
      const body = UI.$("#gm-body .log-output");
      if (body) body.textContent = `Failed to load logs: ${err.message}`;
    }
  }

  function activate() { init(); refresh(true); }

  return { activate };
})();
