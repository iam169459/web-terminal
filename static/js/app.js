/* Application shell: authentication, routing, live metrics feed. */
const App = (() => {
  const VIEWS = {
    dashboard: { title: "Dashboard", mount: () => {} },
    terminal: { title: "Terminal", mount: () => TerminalView.activate() },
    processes: { title: "Processes", mount: () => Processes.activate() },
    services: { title: "Services", mount: () => Services.activate() },
    files: { title: "Files", mount: () => Files.activate() },
  };

  let currentView = null;
  let currentRouteKey = null;
  let metricsSocket = null;
  let reconnectDelay = 1000;
  let session = null;

  /* ── boot ───────────────────────────────────────────────────── */
  function boot() {
    UI.wireCloseButtons();
    wireLogin();
    wireNavigation();
    wireTopbar();
    API.onUnauthorized(showLogin);
    if (API.hasToken()) start(); else showLogin();
  }

  async function start() {
    try {
      session = await API.get("/api/me");
    } catch (err) {
      showLogin();
      return;
    }
    UI.$("#app").classList.remove("hidden");
    UI.$("#login-screen").classList.add("hidden");
    UI.$("#sb-host").textContent = session.host || location.hostname;
    UI.$("#sb-user").textContent = `${session.username} · ${session.shell}`;
    Dashboard.init();
    route(true);
    connectMetrics();
  }

  function showLogin() {
    UI.$("#app").classList.add("hidden");
    UI.$("#login-screen").classList.remove("hidden");
    UI.$("#login-pass").value = "";
    setTimeout(() => UI.$("#login-user").focus(), 50);
  }

  function wireLogin() {
    UI.$("#login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const errorBox = UI.$("#login-error");
      errorBox.classList.add("hidden");
      try {
        const res = await API.post("/api/login", {
          username: UI.$("#login-user").value.trim(),
          password: UI.$("#login-pass").value,
        });
        API.setToken(res.token);
        await start();
      } catch (err) {
        errorBox.textContent = err.message === "Not authenticated" ? "Invalid username or password" : err.message;
        errorBox.classList.remove("hidden");
      }
    });

    UI.$("#logout-btn").addEventListener("click", () => {
      API.setToken("");
      if (metricsSocket) { metricsSocket.onclose = null; metricsSocket.close(); metricsSocket = null; }
      TerminalView.dispose();
      Processes.stopTimer();
      UI.toast("Signed out", "info");
      showLogin();
    });
  }

  /* ── routing ────────────────────────────────────────────────── */
  function parseRoute() {
    const raw = location.hash.replace(/^#\/?/, "");
    const [name, ...rest] = raw.split("/");
    return { name: VIEWS[name] ? name : "dashboard", path: rest.length ? "/" + rest.join("/") : null };
  }

  function wireNavigation() {
    window.addEventListener("hashchange", () => route(false));
    UI.$("#menu-toggle").addEventListener("click", () => UI.$("#sidebar").classList.toggle("open"));
    UI.$$(".nav-item").forEach((item) => {
      item.addEventListener("click", () => {
        UI.$("#sidebar").classList.remove("open");
        if (location.hash === item.getAttribute("href")) route(true);
      });
    });
  }

  function route(force) {
    const { name, path } = parseRoute();
    const key = `${name}|${path || ""}`;
    if (key === currentRouteKey && !force) return;
    currentRouteKey = key;
    currentView = name;

    UI.$$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.nav === name));
    UI.$$(".view").forEach((view) => view.classList.toggle("hidden", view.id !== `view-${name}`));
    UI.$("#page-title").textContent = VIEWS[name].title;
    // A modal (editor, logs, dialog) should never outlive the view that opened it.
    UI.$$(".modal:not(.hidden)").forEach((modal) => modal.classList.add("hidden"));

    if (name === "files" && path) {
      // openPath() initialises the view, so no separate mount() is needed.
      Files.openPath(path);
    } else {
      VIEWS[name].mount();
    }
  }

  /* ── live metrics ───────────────────────────────────────────── */
  function connectMetrics() {
    if (metricsSocket) { metricsSocket.onclose = null; metricsSocket.close(); }
    metricsSocket = new WebSocket(API.ws("/ws/metrics"));

    metricsSocket.onopen = () => {
      reconnectDelay = 1000;
      UI.$("#sb-conn").className = "dot dot-ok";
    };
    metricsSocket.onmessage = (event) => {
      let snapshot;
      try { snapshot = JSON.parse(event.data); } catch (err) { return; }
      updateChrome(snapshot);
      if (currentView === "dashboard") Dashboard.update(snapshot);
    };
    metricsSocket.onclose = () => {
      UI.$("#sb-conn").className = "dot dot-bad";
      if (!API.hasToken()) return;
      setTimeout(connectMetrics, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 1.8, 15000);
    };
  }

  function updateChrome(snapshot) {
    UI.$("#tb-uptime").textContent = `up ${snapshot.uptime_h}`;
    UI.$("#tb-load").textContent = snapshot.load_h ? `load ${snapshot.load_h}` : "";
  }

  /* ── topbar clock ───────────────────────────────────────────── */
  function wireTopbar() {
    const tick = () => {
      const now = new Date();
      UI.$("#tb-clock").textContent = now.toLocaleTimeString([], { hour12: false });
    };
    tick();
    setInterval(tick, 1000);
  }

  return { boot };
})();

document.addEventListener("DOMContentLoaded", App.boot);
