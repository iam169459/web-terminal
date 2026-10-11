/* API client: token storage, JSON requests, websocket URLs. */
const API = (() => {
  const KEY = "webui.token";
  let token = localStorage.getItem(KEY) || "";
  let unauthorizedHandler = null;

  function setToken(value) {
    token = value || "";
    if (token) localStorage.setItem(KEY, token);
    else localStorage.removeItem(KEY);
  }
  function getToken() { return token; }
  function hasToken() { return Boolean(token); }
  function onUnauthorized(fn) { unauthorizedHandler = fn; }

  async function request(path, opts = {}) {
    const headers = Object.assign({}, opts.headers);
    if (token) headers.Authorization = `Bearer ${token}`;

    let body = opts.body;
    if (body && !(body instanceof FormData) && typeof body !== "string") {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }

    const res = await fetch(path, Object.assign({}, opts, { headers, body }));
    if (res.status === 401) {
      setToken("");
      if (unauthorizedHandler) unauthorizedHandler();
      throw new Error("Not authenticated");
    }
    if (!res.ok) {
      let detail = res.statusText || `HTTP ${res.status}`;
      try {
        const data = await res.json();
        if (data && data.detail) detail = data.detail;
      } catch (err) { /* non-JSON error body */ }
      const error = new Error(detail);
      error.status = res.status;
      throw error;
    }
    const type = res.headers.get("content-type") || "";
    return type.includes("json") ? res.json() : res;
  }

  const get = (path, params) => {
    if (params) {
      const qs = new URLSearchParams(
        Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== "")
      ).toString();
      if (qs) path += (path.includes("?") ? "&" : "?") + qs;
    }
    return request(path);
  };
  const post = (path, body) => request(path, { method: "POST", body });

  /** Build a websocket URL that carries the session token. */
  function ws(path, params = {}) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const qs = new URLSearchParams(Object.assign({ token }, params));
    return `${proto}//${location.host}${path}?${qs}`;
  }

  return { get, post, setToken, getToken, hasToken, onUnauthorized, ws, request };
})();
