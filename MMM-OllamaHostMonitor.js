/* global Module */

/* MagicMirror² Module: MMM-OllamaHostMonitor
 *
 * Displays live GPU / memory / Ollama / Hermes stats from the host running your
 * LLMs (e.g. a Mac Studio), fed over MQTT by the companion collector agent.
 *
 * Rendering follows MagicMirror conventions: the title is drawn through the
 * standard module header (getHeader), sizing is relative (em / MM font vars) so
 * it scales with the user's theme, and updates are applied WITHOUT the fade
 * animation so frequent metric refreshes don't flash.
 */
Module.register("MMM-OllamaHostMonitor", {
  defaults: {
    mqttServer: "homeassistant.local",
    mqttPort: 1883,
    mqttUser: "",
    mqttPassword: "",
    topicPrefix: "ollama-host/metrics",
    title: "Mac Studio",  // shown in the standard module header; set "" to hide
    staleAfter: 30,       // seconds without an update before the card greys out
    showCpu: true,        // show CPU usage/power alongside GPU
    showTemps: true,      // show GPU/CPU temperatures
    maxModels: 4          // max Ollama loaded-model rows to render
  },

  getStyles() {
    return ["MMM-OllamaHostMonitor.css"];
  },

  // Use MagicMirror's native module header so the title matches other modules
  // and respects the active theme. A config `header:` overrides the title.
  getHeader() {
    return this.data.header || this.config.title || "";
  },

  start() {
    this.metrics = { system: null, ollama: null, hermes: null, availability: null };
    this._sig = {};  // last-seen payload signature per key, to skip no-op renders
    this.sendSocketNotification("MSM_CONFIG", this.config);
    // Low-frequency, non-animated refresh so staleness + "expires in" stay current
    // even when no new data arrives. No fade => no flashing.
    this.tick = setInterval(() => this.updateDom(), 10000);
  },

  suspend() {
    if (this.tick) clearInterval(this.tick);
    this.tick = null;
  },

  resume() {
    if (!this.tick) this.tick = setInterval(() => this.updateDom(), 10000);
    this.updateDom();
  },

  socketNotificationReceived(notification, payload) {
    if (notification !== "MSM_DATA") return;
    // Retained topics can redeliver identical payloads; only re-render on change.
    const sig = JSON.stringify(payload.data);
    if (this._sig[payload.key] === sig) return;
    this._sig[payload.key] = sig;
    this.metrics[payload.key] = payload.data;
    this.updateDom();  // no speed arg => instant swap, no fade animation
  },

  // ---- helpers ------------------------------------------------------------
  isStale() {
    if (this.metrics.availability === "offline") return true;
    const sys = this.metrics.system;
    if (!sys || !sys.ts) return this.metrics.availability === null;
    return (Date.now() / 1000 - sys.ts) > this.config.staleAfter;
  },

  fmt(v, unit = "", digits = 1) {
    if (v === null || v === undefined || Number.isNaN(v)) return "—";
    return `${Number(v).toFixed(digits)}${unit}`;
  },

  relTime(iso) {
    if (!iso) return null;
    const secs = (new Date(iso).getTime() - Date.now()) / 1000;
    if (Number.isNaN(secs)) return null;
    if (secs <= 0) return "expiring";
    if (secs < 90) return `${Math.round(secs)}s`;
    if (secs < 5400) return `${Math.round(secs / 60)}m`;
    return `${Math.round(secs / 3600)}h`;
  },

  dot(up) {
    const d = document.createElement("span");
    d.className = "msm-dot " + (up ? "msm-up" : "msm-down");
    return d;
  },

  row(label, valueNode) {
    const r = document.createElement("div");
    r.className = "msm-row";
    const l = document.createElement("span");
    l.className = "msm-label dimmed";
    l.innerHTML = label;
    const v = document.createElement("span");
    v.className = "msm-value bright";
    if (typeof valueNode === "string") v.innerHTML = valueNode;
    else v.appendChild(valueNode);
    r.appendChild(l);
    r.appendChild(v);
    return r;
  },

  bar(pct) {
    const wrap = document.createElement("div");
    wrap.className = "msm-bar";
    const fill = document.createElement("div");
    fill.className = "msm-bar-fill";
    const clamped = Math.max(0, Math.min(100, Number(pct) || 0));
    fill.style.width = `${clamped}%`;
    if (clamped >= 85) fill.classList.add("msm-hot");
    wrap.appendChild(fill);
    return wrap;
  },

  section(labelHtml, statusUp) {
    const s = document.createElement("div");
    s.className = "msm-section bright";
    if (statusUp !== undefined) s.appendChild(this.dot(statusUp));
    const span = document.createElement("span");
    span.innerHTML = labelHtml;
    s.appendChild(span);
    return s;
  },

  // ---- render -------------------------------------------------------------
  getDom() {
    const wrapper = document.createElement("div");
    wrapper.className = "msm-wrapper small" + (this.isStale() ? " msm-stale" : "");

    if (this.isStale()) {
      const badge = document.createElement("div");
      badge.className = "msm-badge";
      badge.innerHTML = this.metrics.availability === "offline" ? "offline" : "stale";
      wrapper.appendChild(badge);
    }

    const sys = this.metrics.system || {};
    const ollama = this.metrics.ollama || {};
    const hermes = this.metrics.hermes || {};

    // --- GPU / memory ---
    wrapper.appendChild(this.section("GPU &amp; Memory"));

    const gpuVal = document.createElement("div");
    gpuVal.className = "msm-inline";
    gpuVal.appendChild(this.bar(sys.gpu_usage_pct));
    const gpuText = document.createElement("span");
    gpuText.innerHTML = `${this.fmt(sys.gpu_usage_pct, "%")} · ${this.fmt(sys.gpu_power_w, " W")}`;
    gpuVal.appendChild(gpuText);
    wrapper.appendChild(this.row("GPU", gpuVal));

    if (this.config.showCpu) {
      const cpuVal = document.createElement("div");
      cpuVal.className = "msm-inline";
      cpuVal.appendChild(this.bar(sys.cpu_usage_pct));
      const cpuText = document.createElement("span");
      cpuText.innerHTML = `${this.fmt(sys.cpu_usage_pct, "%")} · ${this.fmt(sys.cpu_power_w, " W")}`;
      cpuVal.appendChild(cpuText);
      wrapper.appendChild(this.row("CPU", cpuVal));
    }

    const memPct = (sys.ram_used_gb && sys.ram_total_gb)
      ? (sys.ram_used_gb / sys.ram_total_gb) * 100 : null;
    const memVal = document.createElement("div");
    memVal.className = "msm-inline";
    memVal.appendChild(this.bar(memPct));
    const memText = document.createElement("span");
    memText.innerHTML = `${this.fmt(sys.ram_used_gb)} / ${this.fmt(sys.ram_total_gb, " GB")}`;
    memVal.appendChild(memText);
    wrapper.appendChild(this.row("Memory", memVal));

    if (sys.swap_used_gb) {
      wrapper.appendChild(this.row("Swap", this.fmt(sys.swap_used_gb, " GB")));
    }
    if (this.config.showTemps && (sys.gpu_temp_c || sys.cpu_temp_c)) {
      wrapper.appendChild(this.row("Temp",
        `GPU ${this.fmt(sys.gpu_temp_c, "°")} · CPU ${this.fmt(sys.cpu_temp_c, "°")}`));
    }

    // --- Ollama ---
    wrapper.appendChild(this.section(
      "Ollama" + (ollama.version ? ` <span class="dimmed">v${ollama.version}</span>` : ""),
      !!ollama.up));

    if (ollama.up) {
      const loaded = ollama.loaded || [];
      if (loaded.length === 0) {
        wrapper.appendChild(this.row("Loaded", `<span class="dimmed">none resident</span>`));
      } else {
        loaded.slice(0, this.config.maxModels).forEach((m) => {
          const rel = this.relTime(m.expires_at);
          const meta = `${this.fmt(m.vram_gb, " GB")}` + (rel ? ` <span class="dimmed">· ${rel}</span>` : "");
          wrapper.appendChild(this.row(this.truncate(m.name, 22), meta));
        });
      }
      if (ollama.installed_count != null) {
        wrapper.appendChild(this.row("Installed",
          `<span class="dimmed">${ollama.installed_count} models</span>`));
      }
    } else {
      wrapper.appendChild(this.row("Status", `<span class="dimmed">not running</span>`));
    }

    // --- Hermes ---
    wrapper.appendChild(this.section("Hermes", !!hermes.up));

    if (hermes.up) {
      if (hermes.model) wrapper.appendChild(this.row("Model", hermes.model));
      wrapper.appendChild(this.row("Usage",
        `${this.fmt(hermes.cpu_pct, "% CPU")} · ${this.fmt(hermes.rss_gb, " GB", 2)}`));
    } else {
      wrapper.appendChild(this.row("Status", `<span class="dimmed">not running</span>`));
    }

    return wrapper;
  },

  truncate(s, n) {
    if (!s) return "—";
    return s.length > n ? s.slice(0, n - 1) + "…" : s;
  }
});
