#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

STATE_PATH = Path("experiments/TeensyCapture/audacity_timeline_state.json")
CAPTURE_SCRIPT = Path("capture_teensy_plus_interface.py")

DEFAULT_PORT = "/dev/cu.usbmodem199934501"
DEFAULT_IFACE_DEVICE = "6"
DEFAULT_IFACE_SAMPLE_RATE = "192000"
DEFAULT_IFACE_CHANNELS = "2"
DEFAULT_IFACE_START_MODE = "arm-gated"
DEFAULT_IFACE_PRE_ROLL = "0.05"
DEFAULT_IFACE_POST_ROLL = "0.05"
DEFAULT_AUDACITY_COMMAND_SPACING = "0.25"
DEFAULT_AUDACITY_RESET_PASSES = "3"
DEFAULT_AUDACITY_PRE_IMPORT_DELAY = "0.10"
DEFAULT_AUDACITY_POST_IMPORT_DELAY = "0.10"
DEFAULT_DURATION_S = 5


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def suggest_trial_and_duration(state: dict) -> tuple[int, int, set[int]]:
    records = state.get("records", [])
    if not isinstance(records, list):
        records = []

    trials: set[int] = set()
    last_duration = None

    for rec in records:
        if not isinstance(rec, dict):
            continue
        trial = rec.get("trial")
        duration_s = rec.get("duration_s")
        if isinstance(trial, int) and trial > 0:
            trials.add(trial)
        if isinstance(duration_s, (int, float)) and duration_s > 0:
            last_duration = int(max(1, round(float(duration_s))))

    suggested_trial = (max(trials) + 1) if trials else 1
    suggested_duration = last_duration if last_duration is not None else DEFAULT_DURATION_S
    return suggested_trial, suggested_duration, trials


def prompt_int(prompt: str, default: int, min_value: int = 1) -> int:
    while True:
        raw = input(f"{prompt} [{default}]: ").strip()
        if raw == "":
            return default
        try:
            value = int(raw)
        except ValueError:
            print("Please enter an integer.")
            continue
        if value < min_value:
            print(f"Please enter a value >= {min_value}.")
            continue
        return value


def build_command(trial: int, duration_s: int) -> list[str]:
    return [
        sys.executable,
        str(CAPTURE_SCRIPT),
        "--port",
        DEFAULT_PORT,
        "--trial",
        str(trial),
        "--duration",
        str(duration_s),
        "--iface-device",
        DEFAULT_IFACE_DEVICE,
        "--iface-sample-rate",
        DEFAULT_IFACE_SAMPLE_RATE,
        "--iface-channels",
        DEFAULT_IFACE_CHANNELS,
        "--iface-start-mode",
        DEFAULT_IFACE_START_MODE,
        "--iface-pre-roll",
        DEFAULT_IFACE_PRE_ROLL,
        "--iface-post-roll",
        DEFAULT_IFACE_POST_ROLL,
        "--iface-trim-to-teensy",
        "--iface-auto-align",
        "--audacity-import",
        "--audacity-command-spacing",
        DEFAULT_AUDACITY_COMMAND_SPACING,
        "--audacity-reset-passes",
        DEFAULT_AUDACITY_RESET_PASSES,
        "--audacity-pre-import-delay",
        DEFAULT_AUDACITY_PRE_IMPORT_DELAY,
        "--audacity-post-import-delay",
        DEFAULT_AUDACITY_POST_IMPORT_DELAY,
    ]


def main() -> int:
    if not CAPTURE_SCRIPT.exists():
        print(f"Capture script not found: {CAPTURE_SCRIPT}")
        return 1

    state = load_state(STATE_PATH)
    suggested_trial, suggested_duration, existing_trials = suggest_trial_and_duration(state)

    print("LTDM capture runner")
    print(f"State file: {STATE_PATH}")

    trial = prompt_int("Trial number", suggested_trial, min_value=1)
    duration_s = prompt_int("Duration (seconds)", suggested_duration, min_value=1)

    if trial in existing_trials:
        print(f"Trial {trial} already exists. Continuing will rerun/replace that trial in timeline state.")

    cmd = build_command(trial, duration_s)
    print("\nRunning:")
    print(" ".join(cmd))
    print("")

    completed = subprocess.run(cmd)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
