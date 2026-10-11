/* Shared DOM helpers, formatters and dialogs. */
const UI = (() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function fmtBytes(n) {
    if (n == null || isNaN(n)) return "-";
    const units = ["B", "KiB", "MiB", "GiB", "TiB", "PiB"];
    let value = Number(n), i = 0;
    while (Math.abs(value) >= 1024 && i < units.length - 1) { value /= 1024; i++; }
    return i === 0 ? `${value} B` : `${value.toFixed(1)} ${units[i]}`;
  }

  function fmtRate(bps) {
    if (bps == null || isNaN(bps)) return "-";
    if (bps < 1) return "0 B/s";
    return `${fmtBytes(bps)}/s`;
  }

  /** Short form for narrow chart axes, e.g. 1.5M / 980B. */
  function fmtBytesCompact(n) {
    if (n == null || isNaN(n)) return "0";
    const units = ["B", "K", "M", "G", "T"];
    let value = Number(n), i = 0;
    while (Math.abs(value) >= 1024 && i < units.length - 1) { value /= 1024; i++; }
    if (i === 0) return `${Math.round(value)}B`;
    return `${value.toFixed(value < 10 ? 1 : 0)}${units[i]}`;
  }

  function fmtPct(n, digits = 1) {
    if (n == null || isNaN(n)) return "-";
    return `${Number(n).toFixed(digits)}%`;
  }

  function fmtDate(ts) {
    if (!ts) return "-";
    const d = ts > 1e12 ? new Date(ts) : new Date(ts * 1000);
    if (isNaN(d)) return "-";
    const pad = (x) => String(x).padStart(2, "0");
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function fmtUptime(seconds) {
    if (seconds == null) return "-";
    let s = Math.floor(seconds);
    const days = Math.floor(s / 86400); s %= 86400;
    const hours = Math.floor(s / 3600); s %= 3600;
    const mins = Math.floor(s / 60);
    const secs = s % 60;
    if (days) return `${days}d ${hours}h`;
    if (hours) return `${hours}h ${mins}m`;
    if (mins) return `${mins}m ${secs}s`;
    return `${secs}s`;
  }

  function meterClass(pct) {
    if (pct >= 90) return "danger";
    if (pct >= 75) return "warn";
    return "ok";
  }

  /* ── toasts ── */
  function toast(message, type = "info", title = "") {
    const host = $("#toasts");
    if (!host) return;
    const node = document.createElement("div");
    node.className = `toast ${type}`;
    const label = title || (type === "err" ? "Error" : type === "ok" ? "Done" : "Note");
    node.innerHTML =
      `<div class="t-body"><div class="t-title">${esc(label)}</div><div class="t-msg">${esc(message)}</div></div>` +
      `<button class="icon-btn" title="Dismiss">✕</button>`;
    node.querySelector("button").onclick = () => node.remove();
    host.appendChild(node);
    setTimeout(() => {
      node.style.transition = "opacity .3s, transform .3s";
      node.style.opacity = "0";
      node.style.transform = "translateX(20px)";
      setTimeout(() => node.remove(), 300);
    }, type === "err" ? 7000 : 4000);
  }

  /* ── modals ── */
  function openModal(id) { $(`#${id}`).classList.remove("hidden"); }
  function closeModal(id) { $(`#${id}`).classList.add("hidden"); }

  function wireCloseButtons() {
    $$("[data-close-modal]").forEach((btn) => {
      btn.addEventListener("click", () => closeModal(btn.dataset.closeModal));
    });
    $$(".modal").forEach((modal) => {
      modal.addEventListener("mousedown", (e) => { if (e.target === modal) modal.classList.add("hidden"); });
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") $$(".modal:not(.hidden)").forEach((m) => m.classList.add("hidden"));
    });
  }

  /** Promise-based confirm dialog rendered into the generic modal. */
  function confirmDialog({ title, message, sub = "", okText = "Confirm", danger = false }) {
    return new Promise((resolve) => {
      const body = $("#gm-body");
      $("#gm-title").textContent = title;
      body.innerHTML =
        `<p class="confirm-text">${esc(message)}</p>` +
        (sub ? `<p class="confirm-sub">${esc(sub)}</p>` : "") +
        `<div class="modal-foot-row">
           <button class="btn" id="cd-cancel">Cancel</button>
           <button class="btn ${danger ? "btn-danger" : "btn-primary"}" id="cd-ok">${esc(okText)}</button>
         </div>`;
      openModal("generic-modal");
      const done = (value) => { closeModal("generic-modal"); resolve(value); };
      $("#cd-cancel").onclick = () => done(false);
      $("#cd-ok").onclick = () => done(true);
    });
  }

  /** Promise-based single-field prompt. Resolves to null when cancelled. */
  function promptDialog({ title, label, value = "", placeholder = "", okText = "OK" }) {
    return new Promise((resolve) => {
      const body = $("#gm-body");
      $("#gm-title").textContent = title;
      body.innerHTML =
        `<div class="field-row">
           <div class="field">
             <label for="pd-input">${esc(label)}</label>
             <input class="input" id="pd-input" placeholder="${esc(placeholder)}">
           </div>
         </div>
         <div class="modal-foot-row">
           <button class="btn" id="pd-cancel">Cancel</button>
           <button class="btn btn-primary" id="pd-ok">${esc(okText)}</button>
         </div>`;
      openModal("generic-modal");
      const input = $("#pd-input");
      input.value = value;
      input.focus();
      input.select();
      const done = (v) => { closeModal("generic-modal"); resolve(v); };
      $("#pd-cancel").onclick = () => done(null);
      $("#pd-ok").onclick = () => done(input.value);
      input.addEventListener("keydown", (e) => {
        if (e.key === "Enter") done(input.value);
        if (e.key === "Escape") done(null);
      });
    });
  }

  /** Show an arbitrary HTML block in the generic modal. */
  function showPanel(title, html) {
    $("#gm-title").textContent = title;
    $("#gm-body").innerHTML = html;
    openModal("generic-modal");
  }

  return {
    $, $$, esc, fmtBytes, fmtBytesCompact, fmtRate, fmtPct, fmtDate, fmtUptime, meterClass,
    toast, openModal, closeModal, wireCloseButtons, confirmDialog, promptDialog, showPanel,
  };
})();
