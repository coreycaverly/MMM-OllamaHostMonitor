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

## Run as a background service (launchd)

On macOS the right way to run a background service is a **launchd LaunchAgent**.
The included [`com.user.ollamahostmonitor.plist`](com.user.ollamahostmonitor.plist)
runs the agent at login, restarts it if it crashes (`KeepAlive`), and writes logs
to `/tmp`. It runs as *your* user (a LaunchAgent, not a system-wide LaunchDaemon),
which is what `macmon` and the Hermes/Ollama process checks need.

### 1. Edit the plist

Open `com.user.ollamahostmonitor.plist` and replace every `/Users/YOU/...` path so
they point at your install — the venv Python, `agent.py`, and `config.toml`:

```xml
<string>/Users/you/MMM-OllamaHostMonitor/agent/.venv/bin/python3</string>
<string>/Users/you/MMM-OllamaHostMonitor/agent/agent.py</string>
...
<key>MSM_CONFIG</key>
<string>/Users/you/MMM-OllamaHostMonitor/agent/config.toml</string>
```

The `PATH` entry already includes `/opt/homebrew/bin` so the `macmon` binary is
found. (Prefer env vars over a config file? You can add `MSM_MQTT_HOST` etc. to the
`EnvironmentVariables` dict instead of pointing at a `config.toml`.)

### 2. Install and start it

```bash
cp com.user.ollamahostmonitor.plist ~/Library/LaunchAgents/

# modern launchctl (macOS 11+):
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.ollamahostmonitor.plist
launchctl kickstart -p gui/$(id -u)/com.user.ollamahostmonitor   # start now

# …or the classic equivalent that still works everywhere:
# launchctl load ~/Library/LaunchAgents/com.user.ollamahostmonitor.plist
```

### 3. Verify / manage

```bash
launchctl print gui/$(id -u)/com.user.ollamahostmonitor | grep -E 'state|pid'   # running?
tail -f /tmp/ollama-host-monitor.err.log                                        # live logs
mosquitto_sub -h <broker> -t 'ollama-host/metrics/#' -v                         # data flowing?
```

Manage the service:

```bash
# stop temporarily
launchctl kill SIGTERM gui/$(id -u)/com.user.ollamahostmonitor

# reload after editing the plist or upgrading the agent
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.user.ollamahostmonitor.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.user.ollamahostmonitor.plist

# remove it entirely
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.user.ollamahostmonitor.plist
rm ~/Library/LaunchAgents/com.user.ollamahostmonitor.plist
```

> **Headless Macs:** a LaunchAgent needs a user session. If the Mac Studio runs
> without anyone logged in, enable auto-login (System Settings → Users & Groups →
> Automatic login) so the agent starts on boot, or convert the plist to a system
> LaunchDaemon in `/Library/LaunchDaemons/` (runs as root — set a `UserName` key
> and a full `PATH`, and note the agent will then measure system-wide processes).

### Alternative: quick foreground / tmux

For a quick always-on setup without launchd you can run it under `caffeinate`
(keeps the Mac awake) inside `tmux`/`screen`:

```bash
caffeinate -is ./.venv/bin/python3 agent.py
```

launchd is preferred for anything permanent — it survives reboots and restarts the
agent on failure.

## Notes

- **Degrades gracefully.** If `macmon` is missing it falls back to `vm_stat`/`sysctl`
  for memory (no GPU). If Ollama is unreachable it publishes `ollama.up = false`.
- **Hermes** has no metrics endpoint, so it's monitored by process (`pgrep -i -f`).
  The default `match = "hermes"` catches both the CLI/gateway and the `Hermes.app`
  desktop app (CPU/RSS are summed across all its processes).
