/* Terminal view: xterm.js over a websocket-attached PTY. */
const TerminalView = (() => {
  let term = null;
  let fitAddon = null;
  let ws = null;
  let initialized = false;
  let resizeTimer = null;

  function init() {
    if (initialized) return;
    initialized = true;

    term = new Terminal({
      fontFamily: 'ui-monospace, "SF Mono", "JetBrains Mono", Menlo, Consolas, monospace',
      fontSize: 13.5,
      lineHeight: 1.25,
      cursorBlink: true,
      scrollback: 5000,
      macOptionIsMeta: true,
      theme: {
        background: "#05070c",
        foreground: "#d7e3f4",
        cursor: "#4f8cff",
        cursorAccent: "#05070c",
        selectionBackground: "rgba(79, 140, 255, .35)",
        black: "#1b2434", red: "#ff5c6c", green: "#2ecc8f", yellow: "#f5a623",
        blue: "#4f8cff", magenta: "#7c5cff", cyan: "#35c2d6", white: "#d7e3f4",
        brightBlack: "#5d6a80", brightRed: "#ff8a95", brightGreen: "#5ce0ae",
        brightYellow: "#ffc46b", brightBlue: "#7fa9ff", brightMagenta: "#a48cff",
        brightCyan: "#6ad7e6", brightWhite: "#ffffff",
      },
    });

    fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    if (typeof WebLinksAddon !== "undefined") {
      term.loadAddon(new WebLinksAddon.WebLinksAddon());
    }
    term.open(UI.$("#terminal"));

    term.onData((data) => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(data);
    });

    fit();
    window.addEventListener("resize", scheduleFit);
    if (window.ResizeObserver) {
      new ResizeObserver(scheduleFit).observe(UI.$("#terminal"));
    }

    UI.$("#term-clear").addEventListener("click", () => term.clear());
    UI.$("#term-reconnect").addEventListener("click", () => { term.reset(); connect(); });
    UI.$("#term-fullscreen").addEventListener("click", toggleFullscreen);
    document.addEventListener("fullscreenchange", () => setTimeout(fit, 120));
  }

  function scheduleFit() {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => { fit(); sendResize(); }, 90);
  }

  function fit() {
    if (!fitAddon) return;
    try { fitAddon.fit(); } catch (err) { /* container hidden */ }
  }

  function sendResize() {
    if (ws && ws.readyState === WebSocket.OPEN && term) {
      ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
    }
  }

  function setStatus(text, kind) {
    const pill = UI.$("#term-status");
    pill.textContent = text;
    pill.className = "pill " + (kind === "ok" ? "pill-ok" : kind === "bad" ? "pill-danger" : "pill-warn");
  }

  function connect() {
    if (!term) init();
    if (ws) {
      ws.onclose = null;
      try { ws.close(); } catch (err) { /* ignore */ }
    }
    setStatus("connecting…", "warn");
    ws = new WebSocket(API.ws("/ws/terminal", { cols: term.cols, rows: term.rows }));

    ws.onopen = () => {
      setStatus(`connected · ${term.cols}×${term.rows}`, "ok");
      term.focus();
      sendResize();
    };
    ws.onmessage = (event) => term.write(typeof event.data === "string" ? event.data : "");
    ws.onerror = () => setStatus("error", "bad");
    ws.onclose = () => {
      setStatus("disconnected", "bad");
      term.write("\r\n\x1b[33m[session closed - press Reconnect]\x1b[0m\r\n");
    };
  }

  function toggleFullscreen() {
    const card = UI.$("#view-terminal .term-card");
    if (!document.fullscreenElement) {
      (card.requestFullscreen ? card.requestFullscreen() : Promise.reject())
        .catch(() => UI.toast("Fullscreen is not available in this browser", "err"));
    } else {
      document.exitFullscreen();
    }
  }

  /** Called when the user navigates to this view. */
  function activate() {
    init();
    setTimeout(() => { fit(); sendResize(); }, 60);
    if (!ws || ws.readyState === WebSocket.CLOSED) connect();
    else term.focus();
  }

  function dispose() {
    if (ws) {
      ws.onclose = null;
      try { ws.close(); } catch (err) { /* ignore */ }
      ws = null;
    }
  }

  return { activate, dispose, connect };
})();
