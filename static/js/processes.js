/* Process manager view. */
const Processes = (() => {
  let sort = "cpu";
  let dir = "desc";
  let search = "";
  let auto = true;
  let timer = null;
  let loaded = false;
  let inflight = false;

  const ACTION_LABEL = { term: "Term", kill: "Kill", stop: "Stop", cont: "Cont" };

  function init() {
    if (loaded) return;
    loaded = true;

    UI.$("#p-refresh").addEventListener("click", () => refresh(true));
    UI.$("#p-auto").addEventListener("change", (e) => {
      auto = e.target.checked;
      if (auto) startTimer(); else stopTimer();
    });

    let debounce = null;
    UI.$("#p-search").addEventListener("input", (e) => {
      clearTimeout(debounce);
      debounce = setTimeout(() => { search = e.target.value.trim(); refresh(true); }, 250);
    });

    UI.$$("#p-table thead th[data-sort]").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (sort === key) dir = dir === "desc" ? "asc" : "desc";
        else { sort = key; dir = key === "name" || key === "user" || key === "status" ? "asc" : "desc"; }
        refresh(true);
      });
    });
    startTimer();
  }

  function startTimer() {
    stopTimer();
    timer = setInterval(() => refresh(false), 3000);
  }
  function stopTimer() { if (timer) { clearInterval(timer); timer = null; } }

  function markSortHeaders() {
    UI.$$("#p-table thead th[data-sort]").forEach((th) => {
      const active = th.dataset.sort === sort;
      th.classList.toggle("sorted", active);
      const label = th.textContent.replace(/[▲▼]\s*$/, "").trim();
      th.textContent = active ? `${label} ${dir === "asc" ? "▲" : "▼"}` : label;
    });
  }

  function statusPill(status) {
    const map = {
      running: "pill-ok", sleeping: "", stopped: "pill-warn", zombie: "pill-danger",
      "disk-sleep": "", idle: "", locked: "pill-warn", traced: "pill-warn",
    };
    return `<span class="pill ${map[status] || ""}">${UI.esc(status)}</span>`;
  }

  async function refresh(showErrors) {
    if (inflight) return;
    inflight = true;
    try {
      const data = await API.get("/api/processes", { sort, direction: dir, search, limit: 500 });
      render(data);
    } catch (err) {
      if (showErrors) UI.toast(err.message, "err");
    } finally {
      inflight = false;
    }
  }

  function render(data) {
    UI.$("#p-count").textContent = `${data.total} shown`;
    UI.$("#nav-proc-count").textContent = data.total;
    markSortHeaders();

    const body = UI.$("#p-body");
    if (!data.processes.length) {
      body.innerHTML = `<tr><td colspan="9" style="text-align:center;color:var(--faint);padding:26px">No matching processes</td></tr>`;
      return;
    }

    body.innerHTML = data.processes.map((p) => {
      const cpuCls = p.cpu_percent >= 80 ? "pill-danger" : p.cpu_percent >= 40 ? "pill-warn" : "";
      return `<tr data-pid="${p.pid}">
          <td class="num">${p.pid}</td>
          <td class="name-cell">${UI.esc(p.name)}</td>
          <td>${UI.esc(p.user)}</td>
          <td class="num"><span class="pill ${cpuCls}">${p.cpu_percent.toFixed(1)}</span></td>
          <td class="num">${p.memory_percent.toFixed(1)}</td>
          <td class="num">${UI.fmtBytes(p.memory_rss)}</td>
          <td>${statusPill(p.status)}</td>
          <td class="cmd" title="${UI.esc(p.cmdline)}">${UI.esc(p.cmdline || "—")}</td>
          <td class="actions-col"><div class="row-actions">
            <button class="btn btn-sm" data-act="term" title="Send SIGTERM">Term</button>
            <button class="btn btn-sm btn-danger" data-act="kill" title="Send SIGKILL">Kill</button>
          </div></td>
        </tr>`;
    }).join("");

    body.querySelectorAll("button[data-act]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const row = btn.closest("tr");
        const pid = Number(row.dataset.pid);
        const name = row.querySelector(".name-cell").textContent;
        const action = btn.dataset.act;
        const ok = await UI.confirmDialog({
          title: action === "kill" ? "Force kill process?" : "Terminate process?",
          message: `Send ${action === "kill" ? "SIGKILL" : "SIGTERM"} to ${name} (PID ${pid})?`,
          sub: row.querySelector(".cmd").textContent,
          okText: action === "kill" ? "Force kill" : "Terminate",
          danger: action === "kill",
        });
        if (!ok) return;
        row.classList.add("busy");
        try {
          await API.post(`/api/processes/${pid}/signal`, { action });
          UI.toast(`${action === "kill" ? "SIGKILL" : "SIGTERM"} sent to ${name} (${pid})`, "ok");
          setTimeout(() => refresh(false), 500);
        } catch (err) {
          UI.toast(err.message, "err");
          row.classList.remove("busy");
        }
      });
    });
  }

  function activate() { init(); refresh(true); }

  return { activate, stopTimer, startTimer };
})();
