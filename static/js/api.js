/* API client: JSON requests and websocket URLs. No auth (local-only UI). */
const API = (() => {
  async function request(path, opts = {}) {
    const headers = Object.assign({}, opts.headers);

    let body = opts.body;
    if (body && !(body instanceof FormData) && typeof body !== "string") {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }

    const res = await fetch(path, Object.assign({}, opts, { headers, body }));
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

  /** Build a websocket URL. */
  function ws(path, params = {}) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const qs = new URLSearchParams(params).toString();
    return `${proto}//${location.host}${path}${qs ? `?${qs}` : ""}`;
  }

  return { get, post, ws, request };
})();
