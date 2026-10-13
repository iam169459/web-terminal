/* File manager view: browse, edit, upload, download, chmod, delete. */
const Files = (() => {
  let cwd = "/";
  let entries = [];
  let bookmarks = [];
  let loaded = false;
  let hasLoaded = false;

  const ICONS = { dir: "📁", file: "📄", link: "🔗" };

  function init() {
    if (loaded) return;
    loaded = true;

    UI.$("#f-refresh").addEventListener("click", () => navigate(cwd, true));
    UI.$("#f-up").addEventListener("click", () => {
      const parent = UI.$("#f-crumbs").dataset.parent;
      if (parent) navigate(parent);
    });
    UI.$("#f-mkdir").addEventListener("click", createFolder);
    UI.$("#f-upload").addEventListener("click", () => UI.$("#f-upload-input").click());
    UI.$("#f-upload-input").addEventListener("change", uploadFiles);
    UI.$("#ed-save").addEventListener("click", saveEditor);

    loadBookmarks();
  }

  async function loadBookmarks() {
    try {
      const data = await API.get("/api/files/bookmarks");
      bookmarks = data.bookmarks || [];
      renderBookmarks();
    } catch (err) { /* sidebar is optional */ }
  }

  function renderBookmarks() {
    UI.$("#f-bookmarks").innerHTML = bookmarks.map((b) =>
      `<div class="bm-item ${b.path === cwd ? "active" : ""}" data-path="${UI.esc(b.path)}">
         <span>${UI.esc(b.label)}</span><span class="sub" style="margin-left:auto;color:var(--faint);font-size:11px">${UI.esc(b.path)}</span>
       </div>`
    ).join("");
    UI.$$("#f-bookmarks .bm-item").forEach((item) => {
      item.addEventListener("click", () => navigate(item.dataset.path));
    });
  }

  function renderCrumbs(path, parent) {
    const crumbs = UI.$("#f-crumbs");
    crumbs.dataset.parent = parent || "";
    const parts = path.split("/").filter(Boolean);
    let html = `<a href="#" data-path="/" class="${parts.length ? "" : "current"}">/</a>`;
    let acc = "";
    parts.forEach((part, i) => {
      acc += "/" + part;
      const last = i === parts.length - 1;
      // The root anchor already renders the leading slash, so only separate later segments.
      html += `${i ? '<span class="sep">/</span>' : ""}<a href="#" data-path="${UI.esc(acc)}" class="${last ? "current" : ""}">${UI.esc(part)}</a>`;
    });
    crumbs.innerHTML = html;
    crumbs.querySelectorAll("a").forEach((a) => {
      a.addEventListener("click", (e) => { e.preventDefault(); navigate(a.dataset.path); });
    });
  }

  async function navigate(path, force) {
    if (!path) path = "/";
    try {
      const data = await API.get("/api/files", { path });
      cwd = data.path;
      entries = data.entries || [];
      hasLoaded = true;
      renderCrumbs(data.path, data.parent);
      render();
      renderBookmarks();
      history.replaceState(null, "", `#/files${cwd === "/" ? "" : cwd}`);
    } catch (err) {
      UI.toast(err.message, "err");
    }
  }

  function render() {
    const body = UI.$("#f-body");
    if (!entries.length) {
      body.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--faint);padding:26px">Empty directory</td></tr>`;
      return;
    }
    body.innerHTML = entries.map((e) => `<tr class="file-row" data-path="${UI.esc(e.path)}" data-dir="${e.is_dir}">
        <td>
          <span class="fname"><span class="ficon">${ICONS[e.type] || "📄"}</span>${UI.esc(e.name)}</span>
          ${e.target ? `<div class="ftarget">→ ${UI.esc(e.target)}</div>` : ""}
        </td>
        <td class="num">${e.is_dir ? "—" : UI.fmtBytes(e.size)}</td>
        <td>${UI.esc(e.owner)}:${UI.esc(e.group)}</td>
        <td class="num">${UI.esc(e.mode_octal)}</td>
        <td>${UI.esc(e.mtime_h)}</td>
        <td class="actions-col"><div class="row-actions">
          ${e.is_dir
            ? `<button class="btn btn-sm" data-act="open">Open</button>`
            : `<button class="btn btn-sm" data-act="edit">Edit</button>
               <button class="btn btn-sm" data-act="download">⬇</button>`}
          <button class="btn btn-sm" data-act="chmod">Mode</button>
          <button class="btn btn-sm" data-act="rename">Rename</button>
          <button class="btn btn-sm btn-danger" data-act="delete">Del</button>
        </div></td>
      </tr>`).join("");

    body.querySelectorAll("tr.file-row").forEach((row) => {
      const path = row.dataset.path;
      const isDir = row.dataset.dir === "true";
      row.querySelector(".fname").addEventListener("click", () => (isDir ? navigate(path) : openEditor(path)));
      row.querySelectorAll("button[data-act]").forEach((btn) => {
        btn.addEventListener("click", () => handleAction(btn.dataset.act, path, isDir, row));
      });
    });
  }

  async function handleAction(act, path, isDir, row) {
    const name = path.split("/").pop();
    try {
      if (act === "open") return navigate(path);
      if (act === "edit") return openEditor(path);
      if (act === "download") {
        window.location.href = `/api/files/download?path=${encodeURIComponent(path)}`;
        return;
      }
      if (act === "chmod") {
        const current = row.children[3].textContent.trim();
        const mode = await UI.promptDialog({
          title: "Change permissions", label: "Octal mode", value: current, placeholder: "755", okText: "Apply",
        });
        if (!mode) return;
        await API.post("/api/files/chmod", { path, mode: mode.trim() });
        UI.toast(`${name} is now ${mode.trim()}`, "ok");
        return navigate(cwd, true);
      }
      if (act === "rename") {
        const next = await UI.promptDialog({
          title: "Rename", label: "New name", value: name, okText: "Rename",
        });
        if (!next || next === name) return;
        await API.post("/api/files/rename", { path, new_name: next });
        UI.toast(`Renamed to ${next}`, "ok");
        return navigate(cwd, true);
      }
      if (act === "delete") {
        const recursive = isDir;
        const ok = await UI.confirmDialog({
          title: recursive ? "Delete folder and contents?" : "Delete file?",
          message: `This permanently removes ${name}.`,
          sub: path,
          okText: "Delete", danger: true,
        });
        if (!ok) return;
        await API.post("/api/files/delete", { path, recursive });
        UI.toast(`Deleted ${name}`, "ok");
        return navigate(cwd, true);
      }
    } catch (err) {
      UI.toast(err.message, "err");
    }
  }

  async function createFolder() {
    const name = await UI.promptDialog({ title: "New folder", label: "Folder name", placeholder: "my-folder", okText: "Create" });
    if (!name) return;
    try {
      await API.post("/api/files/mkdir", { path: `${cwd.replace(/\/$/, "")}/${name}` });
      UI.toast(`Created ${name}`, "ok");
      navigate(cwd, true);
    } catch (err) {
      UI.toast(err.message, "err");
    }
  }

  async function uploadFiles(event) {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    let done = 0;
    for (const file of files) {
      const form = new FormData();
      form.append("path", cwd);
      form.append("file", file, file.name);
      try {
        await API.post("/api/files/upload", form);
        done++;
      } catch (err) {
        UI.toast(`${file.name}: ${err.message}`, "err");
      }
    }
    event.target.value = "";
    if (done) UI.toast(`Uploaded ${done} file${done > 1 ? "s" : ""} to ${cwd}`, "ok");
    navigate(cwd, true);
  }

  /* ── editor ── */
  let editingPath = null;

  async function openEditor(path) {
    try {
      const data = await API.get("/api/files/read", { path });
      if (data.binary) {
        UI.showPanel("Binary file", `<p class="confirm-text">${UI.esc(data.note)}</p><p class="confirm-sub">${UI.esc(path)}</p>`);
        return;
      }
      editingPath = path;
      UI.$("#ed-title").textContent = path;
      UI.$("#ed-meta").textContent = `${data.size_h} · ${data.mode_octal} · ${data.owner}:${data.group} · ${data.encoding}`;
      UI.$("#ed-text").value = data.content || "";
      UI.$("#ed-status").textContent = "";
      UI.openModal("editor-modal");
      setTimeout(() => UI.$("#ed-text").focus(), 60);
    } catch (err) {
      UI.toast(err.message, "err");
    }
  }

  async function saveEditor() {
    if (!editingPath) return;
    const btn = UI.$("#ed-save");
    btn.disabled = true;
    UI.$("#ed-status").textContent = "Saving…";
    try {
      const res = await API.post("/api/files/write", { path: editingPath, content: UI.$("#ed-text").value });
      UI.$("#ed-status").textContent = `Saved ${UI.fmtBytes(res.bytes)} at ${new Date().toLocaleTimeString()}`;
      UI.toast(`Saved ${editingPath.split("/").pop()}`, "ok");
    } catch (err) {
      UI.$("#ed-status").textContent = "";
      UI.toast(err.message, "err");
    } finally {
      btn.disabled = false;
    }
  }

  function activate() {
    init();
    if (!hasLoaded) navigate(cwd, true);
  }

  function openPath(path) {
    init();
    cwd = path;
    navigate(path);
  }

  return { activate, openPath };
})();
