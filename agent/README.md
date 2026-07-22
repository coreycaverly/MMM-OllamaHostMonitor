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

### Recommended: use the installer script

The plist ships with `/Users/YOU/...` placeholder paths. Rather than hand-editing
it, run the installer — it fills in the real paths (from its own location),
validates the result, copies it into `~/Library/LaunchAgents/`, and (re)loads the
service:

```bash
cd MMM-OllamaHostMonitor/agent
./install-service.sh
```

That's it. Skip to [Verify / manage](#3-verify--manage) below. The rest of this
section documents the manual steps the script performs.

> ⚠️ **Do not** copy the abbreviated XML snippet below into the plist file — it's an
> excerpt (note the `...`), not a complete plist. Editing the real
> `com.user.ollamahostmonitor.plist` is what the script does for you.

### 1. Edit the plist (manual)

Open the real `com.user.ollamahostmonitor.plist` file and replace every
`/Users/YOU/...` path so they point at your install — the venv Python, `agent.py`,
and `config.toml`. These are the only lines that change (shown as an excerpt):

```xml
<string>/Users/you/MMM-OllamaHostMonitor/agent/.venv/bin/python3</string>
<string>/Users/you/MMM-OllamaHostMonitor/agent/agent.py</string>
<!-- ...the rest of the file stays as-is... -->
<key>MSM_CONFIG</key>
<string>/Users/you/MMM-OllamaHostMonitor/agent/config.toml</string>
```

The `PATH` entry already includes `/opt/homebrew/bin` so the `macmon` binary is
found. (Prefer env vars over a config file? You can add `MSM_MQTT_HOST` etc. to the
`EnvironmentVariables` dict instead of pointing at a `config.toml`.)

### 2. Install and start it (manual)

```bash
cp com.user.ollamahostmonitor.plist ~/Library/LaunchAgents/
plutil -lint ~/Library/LaunchAgents/com.user.ollamahostmonitor.plist   # sanity check

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

## Home Assistant

The agent can publish [MQTT discovery](https://www.home-assistant.io/integrations/mqtt/#mqtt-discovery)
configs so every metric auto-registers as a Home Assistant entity — no YAML. Enable
it in `config.toml`:

```toml
[homeassistant]
enabled = true
discovery_prefix = "homeassistant"  # match HA's MQTT discovery prefix
node_id = "ollama_host"             # used in discovery topics + unique_ids
device_name = "Ollama Host"         # device name shown in Home Assistant
```

Restart the agent. All entities appear under one HA **device** (`device_name`) and
share the availability topic, so they show *unavailable* when the Mac/agent stops:

- **Sensors:** GPU/CPU usage & power, system power, memory used/total, swap, GPU/CPU
  temperature, Ollama loaded-model count, Ollama installed count.
- **Binary sensors** (`running`): Ollama, Hermes.
- The **Ollama Loaded Models** sensor exposes the full model list (name, VRAM,
  context length, expiry) as **attributes**, and Hermes' model/process count as
  attributes on its binary sensor.

Discovery configs are retained and re-published on every reconnect. To remove the
entities later, set `enabled = false` and delete the retained `homeassistant/…/config`
topics (e.g. `mosquitto_pub -r -n -t homeassistant/sensor/ollama_host/gpu_usage/config`),
or remove the device from HA's MQTT integration.

## Troubleshooting

### Works when run manually, but not as a service

Almost always a bad plist or a service that never loaded. Check:

```bash
# Is it actually loaded and running?
launchctl print gui/$(id -u)/com.user.ollamahostmonitor | grep -E 'state = |pid = '
# Is the installed plist valid and complete (no /Users/YOU placeholders, ~1.5 KB)?
plutil -lint ~/Library/LaunchAgents/com.user.ollamahostmonitor.plist
wc -c    ~/Library/LaunchAgents/com.user.ollamahostmonitor.plist
grep -c '/Users/YOU' ~/Library/LaunchAgents/com.user.ollamahostmonitor.plist   # want 0
```

If the file is tiny or has placeholders, you edited/copied the wrong thing — just run
`./install-service.sh`, which regenerates it correctly and reloads the service. No log
files in `/tmp` at all is a sign the service never started (bad plist).

### No GPU/CPU usage

GPU, CPU and memory all come from the same `macmon` sample. If **memory shows but
GPU/CPU are blank**, the agent didn't get usable `macmon` output and fell back to
`vm_stat` (memory only). Diagnose:

1. Check the `source` field the agent publishes on `…/system` — `macmon` means it's
   working, `vm_stat` means the fallback is active:
   ```bash
   mosquitto_sub -h <broker> -t 'ollama-host/metrics/system' -C 1 | python3 -m json.tool
   ```
2. Look at the agent log — the startup banner reports the macmon path/version, and a
   warning is logged if it's missing or errors:
   ```bash
   grep -i macmon /tmp/ollama-host-monitor.err.log
   ```
3. Run macmon directly on the Mac as the same user the agent runs as:
   ```bash
   macmon pipe -s 1 | python3 -m json.tool
   ```

Common causes: `macmon` not installed (`brew install macmon`); not on `PATH` under
launchd (the plist sets `PATH` to include `/opt/homebrew/bin` — adjust if Homebrew
lives elsewhere, e.g. Intel `/usr/local/bin`). The parser tolerates macmon
version/schema differences field-by-field, so a single odd field no longer blanks the
rest — if you still see gaps, please open an issue with your `macmon --version` and a
sample line.

## Notes

- **Degrades gracefully.** If `macmon` is missing it falls back to `vm_stat`/`sysctl`
  for memory (no GPU). If Ollama is unreachable it publishes `ollama.up = false`.
- **Hermes** has no metrics endpoint, so it's monitored by process (`pgrep -i -f`).
  The default `match = "hermes"` catches both the CLI/gateway and the `Hermes.app`
  desktop app (CPU/RSS are summed across all its processes).
