/* Dashboard view: gauges, history charts and detail panels. */
const Dashboard = (() => {
  let cpuGauge, memGauge, batGauge, tempGauge;
  let cpuChart, memChart, netChart;
  let coresBuilt = false;

  function init() {
    cpuGauge = new Charts.Gauge(UI.$("#g-cpu"), { warnAt: 70, dangerAt: 88 });
    memGauge = new Charts.Gauge(UI.$("#g-mem"), { warnAt: 75, dangerAt: 90 });
    batGauge = new Charts.Gauge(UI.$("#g-bat"), { warnAt: 30, dangerAt: 15, color: "#2ecc8f" });
    tempGauge = new Charts.Gauge(UI.$("#g-temp"), { warnAt: 70, dangerAt: 85, max: 100, color: "#f5a623" });

    cpuChart = new Charts.LineChart(UI.$("#ch-cpu"), {
      max: 100, points: 90,
      series: [{ color: "#4f8cff" }, { color: "#7c5cff", fill: false }],
      yFmt: (v) => `${Math.round(v)}%`,
    });
    memChart = new Charts.LineChart(UI.$("#ch-mem"), {
      max: 100, points: 90,
      series: [{ color: "#4f8cff" }, { color: "#7c5cff", fill: false }],
      yFmt: (v) => `${Math.round(v)}%`,
    });
    netChart = new Charts.LineChart(UI.$("#ch-net"), {
      max: "auto", points: 90, padLeft: 46,
      series: [{ color: "#4f8cff" }, { color: "#7c5cff" }],
      yFmt: (v) => UI.fmtBytesCompact(v),
    });
  }

  /* ── small builders ─────────────────────────────────────────── */
  function meterRow(name, sub, valueLabel, pct, cls) {
    return `<div class="list-row">
        <div class="row-top">
          <span class="name">${UI.esc(name)}</span>
          ${sub ? `<span class="sub">${UI.esc(sub)}</span>` : ""}
          <span class="val">${UI.esc(valueLabel)}</span>
        </div>
        <div class="meter ${cls || UI.meterClass(pct)}"><i style="width:${Math.max(0, Math.min(100, pct))}%"></i></div>
      </div>`;
  }

  function setList(id, html, empty) {
    const node = UI.$(id);
    node.innerHTML = html || `<div class="list-row"><div class="row-top"><span class="sub">${UI.esc(empty || "Nothing to show")}</span></div></div>`;
  }

  /* ── sections ───────────────────────────────────────────────── */
  function renderSystem(ov) {
    UI.$("#d-hostname").textContent = ov.hostname || "-";
    UI.$("#d-kernel").textContent = `${ov.kernel || "-"} (${ov.arch || "?"})`;
    UI.$("#d-arch").textContent = ov.arch || "-";
    UI.$("#d-os").textContent = ov.os || "-";
    UI.$("#d-boot").textContent = UI.fmtDate(ov.boot_time);
  }

  function renderCpu(cpu, loadH) {
    cpuGauge.set(cpu.percent);
    UI.$("#d-cpu-pct").textContent = UI.fmtPct(cpu.percent, 0);
    UI.$("#d-cpu-cores").textContent = `${cpu.cores_logical || "?"} threads`;
    const freq = cpu.frequency && cpu.frequency.current ? `${Math.round(cpu.frequency.current)} MHz` : "frequency n/a";
    UI.$("#d-cpu-freq").textContent = cpu.load_avg
      ? `load ${cpu.load_avg.map((v) => v.toFixed(2)).join(" · ")} · ${freq}`
      : freq;
    UI.$("#d-load").textContent = loadH ? `load ${loadH}` : "";

    const host = UI.$("#d-cores-bars");
    const cores = cpu.per_core || [];
    if (!coresBuilt || host.children.length !== cores.length) {
      host.innerHTML = cores
        .map((_, i) => `<div class="core-row"><span class="lbl">cpu${i}</span><div class="meter"><i></i></div><span class="pct">0%</span></div>`)
        .join("");
      coresBuilt = true;
    }
    cores.forEach((value, i) => {
      const row = host.children[i];
      if (!row) return;
      const bar = row.querySelector("i");
      bar.style.width = `${Math.max(0, Math.min(100, value))}%`;
      row.querySelector(".meter").className = `meter ${UI.meterClass(value)}`;
      row.querySelector(".pct").textContent = `${value.toFixed(0)}%`;
    });

    const loadPerCore = cpu.load_avg && cpu.cores_logical ? (cpu.load_avg[0] / cpu.cores_logical) * 100 : 0;
    cpuChart.push([cpu.percent, Math.min(loadPerCore, 100)]);
  }

  function renderMemory(mem) {
    memGauge.set(mem.percent);
    UI.$("#d-mem-pct").textContent = UI.fmtPct(mem.percent, 0);
    UI.$("#d-mem-used").textContent = `${mem.used_h} / ${mem.total_h}`;
    UI.$("#d-mem-swap").textContent = mem.swap_total
      ? `swap ${mem.swap_used_h} / ${mem.swap_total_h} (${UI.fmtPct(mem.swap_percent, 0)})`
      : "no swap";
    memChart.push([mem.percent, mem.swap_total ? mem.swap_percent : 0]);
  }

  function renderBattery(bat) {
    const card = UI.$("#card-battery");
    if (!bat || !bat.present) {
      card.style.opacity = ".55";
      batGauge.set(0);
      UI.$("#d-bat-pct").textContent = "N/A";
      UI.$("#d-bat-icon").textContent = "🚫";
      UI.$("#d-bat-state").textContent = "no battery";
      UI.$("#d-bat-state").className = "pill";
      UI.$("#d-bat-time").textContent = "This machine reports no battery";
      return;
    }
    card.style.opacity = "";
    batGauge.set(bat.percent);
    UI.$("#d-bat-pct").textContent = UI.fmtPct(bat.percent, 0);
    UI.$("#d-bat-icon").textContent = bat.plugged ? "🔌" : "🔋";

    const state = UI.$("#d-bat-state");
    state.textContent = bat.state;
    state.className = "pill " + (bat.plugged ? "pill-ok" : bat.percent <= 15 ? "pill-danger" : "pill-warn");

    let detail;
    if (bat.plugged) detail = bat.percent >= 99.5 ? "Fully charged" : "Charging on AC";
    else if (bat.time_left_h) detail = `${bat.time_left_h} remaining`;
    else detail = "Discharging · time remaining unknown";
    UI.$("#d-bat-time").textContent = detail;
  }

  function renderTemps(temps) {
    const chip = UI.$("#d-temp-chip");
    if (!temps.available) {
      chip.textContent = "no sensors";
      chip.className = "pill";
      UI.$("#d-temp-pct").textContent = "N/A";
      UI.$("#d-temp-label").textContent = "thermal info unavailable";
      UI.$("#d-temp-crit").textContent = "";
      setList("#d-temps", "", "No thermal sensors exposed by the kernel");
      UI.$("#d-temp-count").textContent = "0 sensors";
      tempGauge.set(0);
      return;
    }

    const max = temps.max;
    tempGauge.max = 100;
    tempGauge.value = max ? max.current : 0;
    tempGauge.render();
    UI.$("#d-temp-pct").textContent = max ? `${max.current}°C` : "-";
    UI.$("#d-temp-label").textContent = max ? max.label : "-";
    UI.$("#d-temp-crit").textContent = max && max.critical ? `critical at ${max.critical}°C` : "critical threshold unknown";
    chip.textContent = max ? max.chip : "";
    chip.className = "pill " + (max && max.critical && max.current >= max.critical - 10 ? "pill-danger" : "");

    UI.$("#d-temp-count").textContent = `${temps.zones.length} sensors`;
    setList("#d-temps", temps.zones.map((z) => {
      const limit = z.critical || z.high || 100;
      const pct = (z.current / limit) * 100;
      return meterRow(z.label, z.chip !== z.label ? z.chip : "", `${z.current}°C`, pct, UI.meterClass(pct));
    }).join(""));
  }

  function renderFans(fans) {
    UI.$("#d-fan-count").textContent = fans.available
      ? `${fans.sensors.length} fan${fans.sensors.length === 1 ? "" : "s"}`
      : "none";
    if (!fans.available) {
      setList("#d-fans", "", "No fan sensors exposed by the kernel");
      return;
    }
    const maxRpm = Math.max(...fans.sensors.map((f) => f.rpm), 1);
    setList("#d-fans", fans.sensors.map((f) =>
      meterRow(f.label, f.chip !== f.label ? f.chip : "", `${f.rpm} RPM`, (f.rpm / maxRpm) * 100, "ok")
    ).join(""));
  }

  function renderDisks(disks) {
    UI.$("#d-disk-count").textContent = `${disks.length} mounted`;
    setList("#d-disks", disks.map((d) =>
      meterRow(d.mountpoint, `${d.device} · ${d.fstype}`, `${d.used_h} / ${d.total_h}`, d.percent)
    ).join(""), "No disks");
  }

  function renderNetwork(net) {
    const total = net.totals || {};
    UI.$("#d-net-total").textContent = total.recv_total_h ? `↓ ${total.recv_total_h} ↑ ${total.sent_total_h}` : "";
    const list = (net.interfaces || []).filter((i) => i.is_up || i.sent_rate > 0 || i.recv_rate > 0);
    setList("#d-net", list.map((iface) => {
      const addrs = (iface.addresses || []).map((a) => a.address).join(", ");
      return meterRow(
        iface.name,
        addrs ? `${iface.is_up ? "up" : "down"} · ${addrs}` : (iface.is_up ? "up" : "down"),
        `↓ ${iface.recv_rate_h}  ↑ ${iface.sent_rate_h}`,
        Math.min(100, (Math.max(iface.recv_rate, iface.sent_rate) / (1024 * 1024)) * 100),
        "ok"
      );
    }).join(""), "No interfaces");
    // Chart the busiest interface so the graph stays meaningful on multi-NIC hosts.
    const busiest = list[0];
    netChart.push([busiest ? busiest.sent_rate : 0, busiest ? busiest.recv_rate : 0]);
  }

  function renderTopProcs(summary) {
    const counts = summary.counts || {};
    UI.$("#d-proc-count").textContent = `${counts.total || 0} total · ${counts.running || 0} running`;
    setList("#d-top-procs", summary.top.map((p) =>
      meterRow(p.name, `pid ${p.pid}`, `${p.cpu}% cpu · ${p.mem}% mem`, Math.min(100, p.cpu), UI.meterClass(p.cpu))
    ).join(""), "No processes");
  }

  /* ── entry point ────────────────────────────────────────────── */
  function update(snapshot) {
    renderSystem(snapshot.overview);
    renderCpu(snapshot.cpu, snapshot.load_h);
    renderMemory(snapshot.memory);
    renderBattery(snapshot.battery);
    renderTemps(snapshot.temperatures);
    renderFans(snapshot.fans);
    renderDisks(snapshot.disks);
    renderNetwork(snapshot.network);
    renderTopProcs(snapshot.processes);
  }

  function reset() {
    [cpuChart, memChart, netChart].forEach((c) => c && c.clear());
  }

  return { init, update, reset };
})();
