# Changelog

All notable changes to this project are documented here. This project adheres to
[Semantic Versioning](https://semver.org/).

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
