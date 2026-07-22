# MMM-OllamaHostMonitor — collector agent

Runs on the **Mac Studio** (the LLM host). Collects GPU / memory / Ollama / Hermes
metrics and publishes them to your MQTT broker for the
[MMM-OllamaHostMonitor](../README.md) MagicMirror module — and, if you like, Home
Assistant — to consume.

## What it publishes

Every `interval` seconds, retained JSON to:

| Topic | Contents |
|-------|----------|
| `ollama-host/metrics/system` | `gpu_usage_pct`, `gpu_power_w`, `cpu_usage_pct`, `cpu_power_w`, `sys_power_w`, `ram_used_gb`, `ram_total_gb`, `swap_used_gb`, `swap_total_gb`, `gpu_temp_c`, `cpu_temp_c` |
| `ollama-host/metrics/ollama` | `up`, `version`, `installed_count`, `loaded[]` (`name`, `size_gb`, `vram_gb`, `context_length`, `expires_at`) |
| `ollama-host/metrics/hermes` | `up`, `proc_count`, `cpu_pct`, `rss_gb`, `model` |
| `ollama-host/metrics/availability` | `online` / `offline` (retained; `offline` is the MQTT Last-Will) |

> **Unified memory note:** Apple Silicon shares one memory pool between CPU and GPU.
> `ram_*` is the whole pool; per-model `vram_gb` is what Ollama has resident in it.

## Install

```bash
# 1. Prereqs
brew install macmon                     # sudoless Apple-Silicon metrics
#   Ollama should already be listening on http://127.0.0.1:11434

# 2. Get the agent onto the Mac Studio, then:
cd MMM-OllamaHostMonitor/agent
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# 3. Configure
cp config.example.toml config.toml
$EDITOR config.toml                     # set your MQTT broker host/creds

# 4. Try it in the foreground
./.venv/bin/python3 agent.py
```

Verify from any machine on the network:

```bash
mosquitto_sub -h <broker> -t 'ollama-host/metrics/#' -v
```

## Run at login (launchd)

```bash
# edit the /Users/YOU/... paths inside the plist first
cp com.user.ollamahostmonitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.user.ollamahostmonitor.plist
# logs: /tmp/ollama-host-monitor.{out,err}.log
```

`KeepAlive` restarts the agent if it crashes; `RunAtLoad` starts it at login.

## Notes

- **Degrades gracefully.** If `macmon` is missing it falls back to `vm_stat`/`sysctl`
  for memory (no GPU). If Ollama is unreachable it publishes `ollama.up = false`.
- **Hermes** has no metrics endpoint, so it's monitored by process (`pgrep -i -f`).
  The default `match = "hermes"` catches both the CLI/gateway and the `Hermes.app`
  desktop app (CPU/RSS are summed across all its processes).
