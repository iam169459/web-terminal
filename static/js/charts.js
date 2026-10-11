/* Tiny canvas chart library — no external dependency, DPI aware. */
const Charts = (() => {
  const DPR = () => Math.min(window.devicePixelRatio || 1, 2);

  function sizeCanvas(canvas) {
    const rect = canvas.getBoundingClientRect();
    const dpr = DPR();
    const w = Math.max(Math.floor(rect.width), 10);
    const h = Math.max(Math.floor(rect.height), 10);
    if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
      canvas.width = w * dpr;
      canvas.height = h * dpr;
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    return { ctx, w, h };
  }

  function hexToRgba(hex, alpha) {
    const clean = hex.replace("#", "");
    const num = parseInt(clean.length === 3
      ? clean.split("").map((c) => c + c).join("")
      : clean, 16);
    return `rgba(${(num >> 16) & 255}, ${(num >> 8) & 255}, ${num & 255}, ${alpha})`;
  }

  function watch(canvas, rerender) {
    if (!window.ResizeObserver) {
      window.addEventListener("resize", rerender);
      return;
    }
    let frame = 0;
    new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(rerender);
    }).observe(canvas);
  }

  /* ─────────── radial gauge ─────────── */
  class Gauge {
    constructor(canvas, opts = {}) {
      this.canvas = canvas;
      this.value = 0;
      this.max = opts.max || 100;
      this.color = opts.color || "#4f8cff";
      this.dangerAt = opts.dangerAt ?? 85;
      this.warnAt = opts.warnAt ?? 70;
      this.start = 0.75 * Math.PI;   // 135°
      this.sweep = 1.5 * Math.PI;    // 270°
      watch(canvas, () => this.render());
      this.render();
    }

    set(value, opts = {}) {
      this.value = Math.max(0, Math.min(Number(value) || 0, this.max));
      if (opts.max) this.max = opts.max;
      if (opts.color) this.color = opts.color;
      this.render();
    }

    render() {
      const { ctx, w, h } = sizeCanvas(this.canvas);
      ctx.clearRect(0, 0, w, h);
      const cx = w / 2, cy = h / 2;
      const radius = Math.min(w, h) / 2 - 9;
      const pct = this.value / this.max;

      let color = this.color;
      if (this.value >= this.dangerAt) color = "#ff5c6c";
      else if (this.value >= this.warnAt) color = "#f5a623";

      // track
      ctx.lineWidth = 10;
      ctx.lineCap = "round";
      ctx.strokeStyle = "rgba(255,255,255,.07)";
      ctx.beginPath();
      ctx.arc(cx, cy, radius, this.start, this.start + this.sweep);
      ctx.stroke();

      if (pct > 0.004) {
        const grad = ctx.createLinearGradient(0, h, w, 0);
        grad.addColorStop(0, hexToRgba(color, 0.55));
        grad.addColorStop(1, color);
        ctx.strokeStyle = grad;
        ctx.beginPath();
        ctx.arc(cx, cy, radius, this.start, this.start + this.sweep * pct);
        ctx.stroke();
      }

      // inner disc for depth
      ctx.beginPath();
      ctx.fillStyle = "rgba(255,255,255,.02)";
      ctx.arc(cx, cy, radius - 11, 0, Math.PI * 2);
      ctx.fill();
    }
  }

  /* ─────────── multi-series line chart ─────────── */
  class LineChart {
    constructor(canvas, opts = {}) {
      this.canvas = canvas;
      this.points = opts.points || 90;
      this.max = opts.max === "auto" ? null : (opts.max || 100);
      this.auto = opts.max === "auto";
      this.yFmt = opts.yFmt || ((v) => `${Math.round(v)}`);
      this.padLeft = opts.padLeft || 40;
      this.series = (opts.series || [{ color: "#4f8cff" }]).map((s) => ({
        color: s.color, data: [], fill: s.fill !== false, width: s.width || 2,
      }));
      watch(canvas, () => this.render());
      this.render();
    }

    push(values) {
      this.series.forEach((s, i) => {
        const v = Array.isArray(values) ? values[i] : values;
        s.data.push(v == null ? null : Number(v));
        if (s.data.length > this.points) s.data.shift();
      });
      this.render();
    }

    clear() { this.series.forEach((s) => { s.data = []; }); this.render(); }

    render() {
      const { ctx, w, h } = sizeCanvas(this.canvas);
      ctx.clearRect(0, 0, w, h);
      const padL = this.padLeft, padR = 6, padT = 8, padB = 18;
      const plotW = Math.max(w - padL - padR, 10);
      const plotH = Math.max(h - padT - padB, 10);

      let max = this.max;
      if (this.auto) {
        let peak = 0;
        this.series.forEach((s) => s.data.forEach((v) => { if (v != null && v > peak) peak = v; }));
        max = peak > 0 ? peak * 1.25 : 1;
      }

      // grid + y labels
      ctx.font = "10px ui-monospace, monospace";
      ctx.textBaseline = "middle";
      for (let i = 0; i <= 4; i++) {
        const y = padT + (plotH * i) / 4;
        ctx.strokeStyle = "rgba(255,255,255,.05)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padL, y + 0.5);
        ctx.lineTo(padL + plotW, y + 0.5);
        ctx.stroke();
        ctx.fillStyle = "rgba(139,152,173,.75)";
        ctx.textAlign = "right";
        ctx.fillText(this.yFmt(max * (1 - i / 4)), padL - 7, y);
      }

      const n = this.points;
      const xAt = (i) => padL + (plotW * i) / (n - 1);
      const yAt = (v) => padT + plotH * (1 - Math.max(0, Math.min(v / max, 1)));

      this.series.forEach((s) => {
        const pts = s.data;
        if (!pts.length) return;

        // find the index the history actually starts at so lines do not
        // stretch across the empty leading area
        const first = pts.findIndex((v) => v != null);
        if (first === -1) return;
        const offset = n - pts.length;

        ctx.beginPath();
        let started = false;
        pts.forEach((v, i) => {
          if (v == null) return;
          const x = xAt(i + offset), y = yAt(v);
          if (!started) { ctx.moveTo(x, y); started = true; }
          else ctx.lineTo(x, y);
        });

        if (s.fill) {
          const lastX = xAt(pts.length - 1 + offset);
          const baseY = padT + plotH;
          const area = new Path2D();
          area.moveTo(xAt(first + offset), baseY);
          pts.forEach((v, i) => { if (v != null) area.lineTo(xAt(i + offset), yAt(v)); });
          area.lineTo(lastX, baseY);
          area.closePath();
          const grad = ctx.createLinearGradient(0, padT, 0, baseY);
          grad.addColorStop(0, hexToRgba(s.color, 0.34));
          grad.addColorStop(1, hexToRgba(s.color, 0.0));
          ctx.fillStyle = grad;
          ctx.fill(area);
        }

        ctx.strokeStyle = s.color;
        ctx.lineWidth = s.width;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.stroke();
      });
    }
  }

  return { Gauge, LineChart, watch };
})();
