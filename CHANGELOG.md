# Changelog

All notable changes to this project are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- **GPU/CPU no longer disappear on some Macs.** The macmon parse was all-or-nothing:
  one unexpected field (macmon's JSON shape varies by version) threw and dropped the
  agent to the memory-only `vm_stat` fallback, blanking GPU *and* CPU. Each field is
  now parsed independently, CPU usage falls back to the E/P-core clusters when
  `cpu_usage_pct` is absent, and the agent logs a startup banner + warnings so a
  missing/failing macmon is obvious. The published `source` field (`macmon`/`vm_stat`)
  makes the active path visible.

### Changed
- **Fixed flashing on refresh.** Metric updates now apply without the fade
  animation, and identical retained payloads are skipped, so live data refreshes
  smoothly instead of flickering every few seconds.
- **Native MagicMirror styling.** The title is drawn through the standard module
  header (`getHeader`), colors use MM theme variables (`--color-text*`), and sizing
  is relative (em / MM `.small`) so the module scales with the configured font size
  and fits any region.
- Module pauses its refresh timer on `suspend()` and resumes on `resume()`.

### Added
- `agent/install-service.sh` — one-command launchd installer that fills the plist
  paths from its own location, validates, and (re)loads the service. Avoids the
  hand-edited-plist pitfall where the service silently never loads.
- Troubleshooting for "works manually but not as a service" (validate/size-check the
  installed plist), and expanded collector docs: running as a launchd background
  service (bootstrap/kickstart/bootout, logs, headless-Mac notes, caffeinate/tmux).

## [1.0.0] — 2026-07-22

### Added
- **MagicMirror module** (`MMM-OllamaHostMonitor`) rendering GPU/CPU usage &
  power, unified memory, swap, temperatures, Ollama resident models + VRAM, and
  Hermes process status. Subscribes over MQTT via `node_helper`; greys out on
  stale/offline data.
- **Collector agent** (`agent/agent.py`) for the Mac Studio: gathers metrics from
  `macmon` (sudoless Apple-Silicon GPU/mem), the Ollama REST API
  (`/api/ps`, `/api/tags`, `/api/version`), and the Hermes process, then publishes
  retained JSON to MQTT with an availability Last-Will.
- TOML config, `requirements.txt`, and a launchd LaunchAgent for run-at-login.
- Graceful degradation when `macmon` or Ollama is unavailable.
- Documentation: module + agent READMEs, MQTT topic reference, troubleshooting.
