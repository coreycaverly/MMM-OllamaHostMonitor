#!/usr/bin/env python3
"""MMM-OllamaHostMonitor collector agent.

Runs on the host serving your LLMs (e.g. a Mac Studio). Every `interval`
seconds it collects:
  - system/GPU metrics via `macmon pipe` (sudoless Apple-Silicon metrics)
  - Ollama status via the local REST API (/api/ps, /api/tags, /api/version)
  - Hermes (NousResearch hermes-agent) process status via pgrep/ps

...and publishes three retained JSON messages to MQTT, plus an availability
topic backed by an MQTT Last-Will so subscribers know if the Mac/agent dies.

Designed to degrade gracefully: if macmon or Ollama is missing/unreachable the
relevant fields are null / `up: false` rather than crashing the loop.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

import paho.mqtt.client as mqtt

GIB = 1024 ** 3


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
DEFAULTS = {
    "interval": 3.0,
    "topic_prefix": "ollama-host/metrics",
    "mqtt": {
        "host": "localhost",
        "port": 1883,
        "username": "",
        "password": "",
        "tls": False,
        "client_id": "ollama-host-monitor",
    },
    "macmon": {"path": "macmon", "sample_interval_ms": 250},
    "ollama": {"url": "http://127.0.0.1:11434", "timeout": 3.0},
    "hermes": {"match": "hermes", "model_cmd": ""},
}


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config() -> dict:
    cfg = DEFAULTS
    path = os.environ.get("MSM_CONFIG")
    if not path:
        for cand in (Path(__file__).with_name("config.toml"),
                     Path.home() / ".config" / "ollama-host-monitor" / "config.toml"):
            if cand.exists():
                path = str(cand)
                break
    if path and Path(path).exists():
        with open(path, "rb") as fh:
            cfg = deep_merge(cfg, tomllib.load(fh))
    # env overrides for the most common knobs (handy for launchd)
    env = os.environ
    if env.get("MSM_MQTT_HOST"):
        cfg["mqtt"]["host"] = env["MSM_MQTT_HOST"]
    if env.get("MSM_MQTT_PORT"):
        cfg["mqtt"]["port"] = int(env["MSM_MQTT_PORT"])
    if env.get("MSM_MQTT_USER"):
        cfg["mqtt"]["username"] = env["MSM_MQTT_USER"]
    if env.get("MSM_MQTT_PASSWORD"):
        cfg["mqtt"]["password"] = env["MSM_MQTT_PASSWORD"]
    return cfg


# --------------------------------------------------------------------------- #
# Collectors
# --------------------------------------------------------------------------- #
def _ratio_to_pct(v) -> float | None:
    try:
        return round(float(v) * 100.0, 1)
    except (TypeError, ValueError):
        return None


def _ratio_from_cluster(v):
    """macmon reports per-cluster usage as [freq, ratio]; return the ratio."""
    if isinstance(v, (list, tuple)) and len(v) > 1:
        return v[1]
    if isinstance(v, (int, float)):  # some versions emit a bare ratio
        return v
    return None


def collect_system(cfg: dict) -> dict:
    """GPU/CPU/memory via macmon, with a vm_stat/sysctl fallback for memory.

    Each field is parsed independently: a schema quirk in one field (which varies
    between macmon versions) must never blank out the others. We only fall back to
    vm_stat when macmon yields no usable JSON at all.
    """
    out: dict = {
        "gpu_usage_pct": None, "gpu_power_w": None,
        "cpu_usage_pct": None, "cpu_power_w": None, "sys_power_w": None,
        "ram_used_gb": None, "ram_total_gb": None,
        "swap_used_gb": None, "swap_total_gb": None,
        "gpu_temp_c": None, "cpu_temp_c": None, "source": None,
    }
    macmon = shutil.which(cfg["macmon"]["path"]) or None
    sample = None
    if macmon:
        interval = int(cfg["macmon"]["sample_interval_ms"])
        try:
            # Two samples, keep the last: the first is a warm-up and can read 0.
            proc = subprocess.run(
                [macmon, "pipe", "-s", "2", "-i", str(interval)],
                capture_output=True, text=True,
                timeout=max(6, 2 * interval / 1000 + 6),
            )
            lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
            if lines:
                sample = json.loads(lines[-1])
            else:
                log(f"macmon produced no output (rc={proc.returncode}); "
                    f"stderr: {proc.stderr.strip()[:200]!r}")
        except Exception as exc:  # noqa: BLE001 - keep the loop alive
            log(f"macmon run/parse failed: {exc}")
    elif cfg["macmon"]["path"]:
        log(f"macmon not found on PATH (looked for {cfg['macmon']['path']!r}); "
            f"GPU/CPU unavailable, memory via vm_stat")

    if sample is not None:
        # Parse defensively, field by field.
        out["source"] = "macmon"
        gpu = _get(sample, "gpu_usage")
        out["gpu_usage_pct"] = _ratio_to_pct(_ratio_from_cluster(gpu))
        cpu_ratio = _get(sample, "cpu_usage_pct")
        if cpu_ratio is None:  # older macmon: derive from E/P-core clusters
            e = _ratio_from_cluster(_get(sample, "ecpu_usage"))
            p = _ratio_from_cluster(_get(sample, "pcpu_usage"))
            vals = [x for x in (e, p) if x is not None]
            cpu_ratio = max(vals) if vals else None
        out["cpu_usage_pct"] = _ratio_to_pct(cpu_ratio)
        out["gpu_power_w"] = _round(_get(sample, "gpu_power"))
        out["cpu_power_w"] = _round(_get(sample, "cpu_power"))
        out["sys_power_w"] = _round(_get(sample, "sys_power"))
        mem = _get(sample, "memory") or {}
        out["ram_used_gb"] = _bytes_gb(mem.get("ram_usage"))
        out["ram_total_gb"] = _bytes_gb(mem.get("ram_total"))
        out["swap_used_gb"] = _bytes_gb(mem.get("swap_usage"))
        out["swap_total_gb"] = _bytes_gb(mem.get("swap_total"))
        temp = _get(sample, "temp") or {}
        out["gpu_temp_c"] = _round(temp.get("gpu_temp_avg"))
        out["cpu_temp_c"] = _round(temp.get("cpu_temp_avg"))
        return out

    # No usable macmon data: fall back to memory-only via vm_stat/sysctl.
    try:
        total = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"]))
        out["ram_total_gb"] = round(total / GIB, 1)
        out["ram_used_gb"] = _vm_stat_used_gb()
        out["source"] = "vm_stat"
    except Exception as exc:  # noqa: BLE001
        log(f"memory fallback failed: {exc}")
    return out


def _get(d, key):
    """Safe dict get that tolerates non-dict input."""
    return d.get(key) if isinstance(d, dict) else None


def _vm_stat_used_gb() -> float | None:
    try:
        raw = subprocess.check_output(["vm_stat"], text=True)
    except Exception:
        return None
    page = 16384
    pages = {}
    for ln in raw.splitlines():
        if "page size of" in ln:
            page = int(ln.split("page size of")[1].split("bytes")[0].strip())
        elif ":" in ln:
            k, _, v = ln.partition(":")
            pages[k.strip()] = int(v.strip().rstrip("."))
    used_pages = (pages.get("Pages active", 0) + pages.get("Pages wired down", 0)
                  + pages.get("Pages occupied by compressor", 0))
    return round(used_pages * page / GIB, 1)


def collect_ollama(cfg: dict) -> dict:
    base = cfg["ollama"]["url"].rstrip("/")
    timeout = cfg["ollama"]["timeout"]
    out = {"up": False, "version": None, "installed_count": None, "loaded": []}
    try:
        ps = requests.get(f"{base}/api/ps", timeout=timeout).json()
        out["up"] = True
        for m in ps.get("models", []):
            out["loaded"].append({
                "name": m.get("name") or m.get("model"),
                "size_gb": _bytes_gb(m.get("size")),
                "vram_gb": _bytes_gb(m.get("size_vram")),
                "context_length": m.get("context_length"),
                "expires_at": m.get("expires_at"),
            })
    except Exception as exc:  # noqa: BLE001
        log(f"ollama /api/ps failed: {exc}")
        return out
    for path, key, fn in (
        ("/api/version", "version", lambda j: j.get("version")),
        ("/api/tags", "installed_count", lambda j: len(j.get("models", []))),
    ):
        try:
            out[key] = fn(requests.get(f"{base}{path}", timeout=timeout).json())
        except Exception:  # noqa: BLE001
            pass
    return out


def collect_hermes(cfg: dict) -> dict:
    """Hermes has no metrics endpoint; monitor it at the process level.

    hermes-agent may run either as a CLI/gateway or the Electron desktop app,
    which spawns several helper processes. We aggregate CPU%/RSS across every
    matching PID so the numbers reflect the whole app.
    """
    match = cfg["hermes"]["match"]
    out = {"up": False, "proc_count": 0, "cpu_pct": None, "rss_gb": None,
           "model": None, "backend": None}
    try:
        pids = subprocess.run(["pgrep", "-i", "-f", match],
                              capture_output=True, text=True).stdout.split()
    except Exception as exc:  # noqa: BLE001
        log(f"hermes pgrep failed: {exc}")
        return out
    if not pids:
        return out
    out["up"] = True
    out["proc_count"] = len(pids)
    try:
        ps = subprocess.run(["ps", "-o", "%cpu=,rss=", "-p", ",".join(pids)],
                            capture_output=True, text=True).stdout
        cpu = 0.0
        rss_kb = 0
        for ln in ps.splitlines():
            parts = ln.split()
            if len(parts) >= 2:
                cpu += float(parts[0])
                rss_kb += int(parts[1])
        out["cpu_pct"] = round(cpu, 1)
        out["rss_gb"] = round(rss_kb * 1024 / GIB, 2)
    except Exception as exc:  # noqa: BLE001
        log(f"hermes ps failed: {exc}")
    model_cmd = cfg["hermes"].get("model_cmd")
    if model_cmd:
        try:
            out["model"] = subprocess.check_output(
                model_cmd, shell=True, text=True, timeout=5).strip() or None
        except Exception:  # noqa: BLE001
            pass
    return out


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _bytes_gb(v) -> float | None:
    try:
        return round(int(v) / GIB, 2)
    except (TypeError, ValueError):
        return None


def _round(v, n=1):
    try:
        return round(float(v), n)
    except (TypeError, ValueError):
        return None


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


# --------------------------------------------------------------------------- #
# MQTT
# --------------------------------------------------------------------------- #
def make_client(cfg: dict, avail_topic: str) -> mqtt.Client:
    m = cfg["mqtt"]
    try:  # paho 2.x
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                             client_id=m.get("client_id") or None)
    except (AttributeError, TypeError):  # paho 1.x
        client = mqtt.Client(client_id=m.get("client_id") or None)
    if m.get("username"):
        client.username_pw_set(m["username"], m.get("password") or None)
    if m.get("tls"):
        client.tls_set()
    client.will_set(avail_topic, "offline", qos=1, retain=True)
    return client


def _macmon_banner(cfg: dict) -> None:
    """Log macmon presence/version once at startup — the usual cause of missing
    GPU/CPU is macmon not being found (e.g. wrong PATH under launchd)."""
    path = shutil.which(cfg["macmon"]["path"])
    if not path:
        log(f"WARNING: macmon not found (path={cfg['macmon']['path']!r}); "
            f"GPU/CPU will be empty. Install via `brew install macmon` and ensure "
            f"its dir is on PATH (launchd PATH includes /opt/homebrew/bin).")
        return
    try:
        ver = subprocess.check_output([path, "--version"], text=True, timeout=5).strip()
    except Exception:  # noqa: BLE001
        ver = "unknown version"
    log(f"macmon: {path} ({ver})")


def main() -> int:
    cfg = load_config()
    prefix = cfg["topic_prefix"].rstrip("/")
    avail_topic = f"{prefix}/availability"
    interval = float(cfg["interval"])

    _macmon_banner(cfg)

    client = make_client(cfg, avail_topic)
    running = {"v": True}

    def stop(*_):
        running["v"] = False
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    log(f"connecting to mqtt {cfg['mqtt']['host']}:{cfg['mqtt']['port']}")
    client.connect(cfg["mqtt"]["host"], int(cfg["mqtt"]["port"]), keepalive=60)
    client.loop_start()
    client.publish(avail_topic, "online", qos=1, retain=True)
    log(f"publishing to {prefix}/{{system,ollama,hermes}} every {interval}s")

    try:
        while running["v"]:
            started = time.time()
            for suffix, collector in (
                ("system", collect_system),
                ("ollama", collect_ollama),
                ("hermes", collect_hermes),
            ):
                try:
                    payload = collector(cfg)
                except Exception as exc:  # noqa: BLE001
                    log(f"{suffix} collector crashed: {exc}")
                    payload = {"error": str(exc)}
                payload["ts"] = int(time.time())
                client.publish(f"{prefix}/{suffix}",
                               json.dumps(payload), qos=0, retain=True)
            # sleep the remainder of the interval, staying responsive to signals
            while running["v"] and time.time() - started < interval:
                time.sleep(0.2)
    finally:
        log("shutting down; marking offline")
        client.publish(avail_topic, "offline", qos=1, retain=True)
        time.sleep(0.3)
        client.loop_stop()
        client.disconnect()
    return 0


if __name__ == "__main__":
    sys.exit(main())
