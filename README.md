# MMM-OllamaHostMonitor

A [MagicMirror²](https://magicmirror.builders/) module that shows the live health
of the host running your local LLMs — **GPU utilization & power, unified memory,
[Ollama](https://ollama.com/) resident models + VRAM, and [Hermes](https://github.com/NousResearch/hermes-agent)
process status**. Built for an Apple-Silicon **Mac Studio**, but works on any Mac.

Because macOS exposes no GPU/memory metrics over HTTP — and `hermes-agent` has no
metrics endpoint — a small **collector agent** runs on the host, gathers everything,
and publishes it to your **MQTT broker** (the same one Home Assistant uses). This
module subscribes and renders it. No inbound ports on the Mac, and Home Assistant
can consume the exact same topics for free.

> ⚠️ This repo contains **two pieces**: the MagicMirror module (repo root) and the
> [`agent/`](agent) that runs on the Mac. Both must be set up — see below.

---

## Architecture

```
 Mac Studio (LLM host)                MQTT broker            MagicMirror device
 ┌────────────────────────┐          ┌───────────┐          ┌──────────────────────┐
 │ agent/agent.py         │  publish │           │ subscribe│ MMM-OllamaHostMonitor │
 │  • macmon → GPU / mem  │─────────▶│ Mosquitto │─────────▶│  node_helper → UI     │
 │  • Ollama /api/ps      │          │  / HA      │          │                      │
 │  • Hermes process      │          └───────────┘          └──────────────────────┘
 └────────────────────────┘
     retained topics:  <prefix>/{system,ollama,hermes,availability}
```

The module holds **no polling timer** — it subscribes once and updates as retained
messages arrive, so the card fills in instantly on MagicMirror startup and greys
out (via an MQTT Last-Will) if the host or agent stops publishing.

**Native look & feel:** the title uses MagicMirror's standard module header, colors
come from the active theme (`--color-text*`), and sizing is relative — so it scales
with your configured font size and drops into any region (`top_left`, `top_right`,
`middle_center`, …). Updates are applied without a fade, so live metrics refresh
smoothly instead of flashing.

## What you see

- **GPU & Memory** — GPU utilization (bar) + power draw, CPU usage + power,
  unified memory used/total, swap, and GPU/CPU temperatures.
- **Ollama** — up/down indicator, server version, each resident model with its
  VRAM footprint and idle-unload countdown, and total installed model count.
- **Hermes** — up/down indicator and aggregate CPU%/RSS across its process(es).

> **Unified memory note:** Apple Silicon shares one memory pool between CPU and
> GPU, so "Memory" is the whole pool and each model's VRAM is its slice of it.

---

## Installation

### 1. Collector agent (on the Mac Studio)

See **[agent/README.md](agent/README.md)** for full detail. In short:

```bash
brew install macmon                       # sudoless Apple-Silicon metrics
cd MMM-OllamaHostMonitor/agent
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
cp config.example.toml config.toml        # set your MQTT broker host/creds
./.venv/bin/python3 agent.py              # run in foreground to test
```

Confirm data is flowing from any machine on the network:

```bash
mosquitto_sub -h <broker> -t 'ollama-host/metrics/#' -v
```

### 2. The module (on the MagicMirror device)

```bash
cd ~/MagicMirror/modules
git clone https://github.com/coreycaverly/MMM-OllamaHostMonitor.git
cd MMM-OllamaHostMonitor
npm install                               # pulls in the mqtt client
```

Then add the block below to `~/MagicMirror/config/config.js`.

---

## Configuration

```js
{
  module: "MMM-OllamaHostMonitor",
  position: "top_right",
  config: {
    mqttServer: "homeassistant.local",   // your MQTT broker
    mqttPort: 1883,
    mqttUser: "",                        // if your broker requires auth
    mqttPassword: "",
    topicPrefix: "ollama-host/metrics",    // MUST match the agent's config
    title: "Mac Studio",
    staleAfter: 30,                      // seconds before the card greys out
    showCpu: true,
    showTemps: true,
    maxModels: 4
  }
}
```

| Option | Default | Description |
|--------|---------|-------------|
| `mqttServer` | `homeassistant.local` | MQTT broker hostname/IP |
| `mqttPort` | `1883` | MQTT broker port |
| `mqttUser` / `mqttPassword` | `""` | Broker credentials, if any |
| `topicPrefix` | `ollama-host/metrics` | Must match the agent's `topic_prefix` |
| `title` | `Mac Studio` | Rendered as the standard MagicMirror module header. Set `""` to hide, or use MM's own `header:` key to override. |
| `staleAfter` | `30` | Seconds without data before greying out |
| `showCpu` | `true` | Show the CPU usage/power row |
| `showTemps` | `true` | Show GPU/CPU temperatures |
| `maxModels` | `4` | Max Ollama loaded-model rows to render |

---

## MQTT topic reference

All payloads are retained JSON published by the agent under `topicPrefix`:

| Topic | Example payload |
|-------|-----------------|
| `…/system` | `{"gpu_usage_pct":62.4,"gpu_power_w":18.7,"cpu_usage_pct":9.6,"cpu_power_w":4.1,"sys_power_w":61,"ram_used_gb":41.2,"ram_total_gb":128,"swap_used_gb":0,"gpu_temp_c":47,"cpu_temp_c":45,"ts":1737550000}` |
| `…/ollama` | `{"up":true,"version":"0.5.4","installed_count":12,"loaded":[{"name":"hermes3:8b","size_gb":6.1,"vram_gb":5.0,"context_length":4096,"expires_at":"…"}],"ts":…}` |
| `…/hermes` | `{"up":true,"proc_count":8,"cpu_pct":9.3,"rss_gb":1.28,"model":null,"ts":…}` |
| `…/availability` | `online` / `offline` (retained; `offline` is the MQTT Last-Will) |

### Bonus: Home Assistant

The agent has built-in **Home Assistant MQTT discovery** — flip `[homeassistant]
enabled = true` in its config and every metric auto-registers as an HA entity under
one device (loaded models exposed as attributes on a single sensor). No extra
collection, same broker. See [agent/README.md](agent/README.md#home-assistant).

---

## Troubleshooting

| Symptom | Check |
|---------|-------|
| Card shows **offline/stale** | Is the agent running on the Mac? `mosquitto_sub -t '<prefix>/#' -v` should show updates. |
| **No card at all** | `npm install` run in the module folder? Check MagicMirror logs for `[MMM-OllamaHostMonitor]`. |
| **GPU/CPU show — but memory works** | The agent fell back to `vm_stat` (macmon missing or unreadable). Check the `source` field in `…/system` (`macmon` vs `vm_stat`) and the agent's `err` log. See [agent/README.md](agent/README.md#no-gpucpu-usage). |
| **Ollama "not running"** | Agent host can reach `http://127.0.0.1:11434`? Confirm `ollama serve` is up. |
| `topicPrefix` mismatch | The module's `topicPrefix` must equal the agent's `topic_prefix`. |

---

## License

[MIT](LICENSE) © Corey Caverly
