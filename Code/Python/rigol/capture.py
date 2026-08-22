# rigol_capture.py
"""
RAW waveform capture from Rigol DS1054Z via LAN/VXI-11.
6,000,000 points per channel at 250 MSa/s.

HDF5 stores raw ADC counts (uint8) as the primary dataset.
Scaling factors stored as dataset attributes for post-hoc
calibration:
    V = (raw - yreference - yorigin) * yincrement

Also saves a PNG screenshot of the scope screen at capture time.

Requirements:
    pip install ds1054z python-vxi11 h5py matplotlib numpy pillow
"""

from ds1054z import DS1054Z
from rigol.common import (
    CHANNELS, CHANNEL_LABELS,
    counts_to_voltage, build_time_axis,
    make_scope_plot,
)
import argparse
import getpass
import json
import re
import numpy as np
import h5py
from datetime import datetime
from pathlib import Path
from core.experiment_profile import load_experiment_profile, prompt_experiment_profile, save_experiment_profile
from rigol.screen import save_screen
import questionary
import sys
import time
from core.path_layout import build_trial_paths, existing_trial_numbers as list_existing_trials, next_capture_dir, safe_name

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

from rigol.common import SCOPE_IP
OUTPUT_HDF5 = "rigol_capture.h5"
OUTPUT_PNG  = "rigol_capture.png"
SCREEN_PNG  = "rigol_screen.png"
EXPERIMENTS_DIR = Path("experiments")
TRIAL_META_NAME = "scope_capture_meta.json"
TRIAL_DIR_PREFIX = "trial_"
TRIAL_HDF5_NAME = "rigol_capture.h5"
TRIAL_PNG_NAME = "rigol_capture.png"
TRIAL_SCREEN_NAME = "rigol_screen.png"


# ─────────────────────────────────────────────
# HELPER: Experiment metadata and folder utilities
# ─────────────────────────────────────────────

def parse_preamble(preamble_str: str) -> dict:
    fields   = preamble_str.strip().split(",")
    fmt_map  = {0: "BYTE", 1: "WORD", 2: "ASC"}
    type_map = {0: "NORM", 1: "MAX",  2: "RAW"}
    return {
        "format"    : fmt_map.get(int(fields[0]),  fields[0]),
        "type"      : type_map.get(int(fields[1]), fields[1]),
        "points"    : int(fields[2]),
        "count"     : int(fields[3]),
        "xincrement": float(fields[4]),
        "xorigin"   : float(fields[5]),
        "xreference": float(fields[6]),
        "yincrement": float(fields[7]),
        "yorigin"   : float(fields[8]),
        "yreference": float(fields[9]),
    }


def _decode_attr(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def load_previous_metadata() -> dict[str, str]:
    """Loads metadata from the most recent previous rigol_capture HDF5 file."""
    files = sorted(
        Path(".").rglob("rigol_capture.h5"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return {}

    try:
        with h5py.File(files[0], "r") as f:
            return {k: _decode_attr(v) for k, v in f.attrs.items()}
    except Exception:
        return {}


def experiment_dir_for_title(title: str) -> Path:
    return EXPERIMENTS_DIR / safe_name(title)


def existing_trial_numbers(exp_dir: Path) -> list[int]:
    return list_existing_trials(exp_dir)


def load_trial_manifest(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_trial_manifest(path: Path, manifest: dict) -> None:
    path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def parse_args():
    parser = argparse.ArgumentParser(description="Capture Rigol DS1054Z data for an LTDM trial.")
    parser.add_argument("--experiment", help="Experiment title to attach this scope capture to")
    parser.add_argument("--trial", type=int, help="Trial number to attach this scope capture to")
    return parser.parse_args()


def ask_experiment_title(default_title: str) -> str:
    title = questionary.text(
        "Experiment name / title:",
        default=default_title,
    ).ask()
    if title is None:
        print("No experiment title entered. Exiting.")
        sys.exit(0)
    title = title.strip()
    if not title:
        print("Experiment title is required.")
        sys.exit(0)
    return title


def prompt_scope_channel_labels(defaults: dict[str, str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for ch in CHANNELS:
        key = f"channel_label_{ch}"
        labels[key] = questionary.text(
            f"Channel {ch} label:",
            default=defaults.get(key, CHANNEL_LABELS[ch]),
        ).ask() or defaults.get(key, CHANNEL_LABELS[ch])
    return {k: str(v).strip() for k, v in labels.items()}


def resolve_scope_channel_labels(defaults: dict[str, str], prompt_for_missing: bool) -> dict[str, str]:
    if prompt_for_missing:
        return prompt_scope_channel_labels(defaults)

    labels: dict[str, str] = {}
    for ch in CHANNELS:
        key = f"channel_label_{ch}"
        labels[key] = str(defaults.get(key, CHANNEL_LABELS[ch])).strip()
    return labels


def ask_trial_number(exp_dir: Path, default_trial: int) -> int:
    default_str = str(default_trial)
    while True:
        answer = questionary.text(
            "Trial number:",
            default=default_str,
        ).ask()
        if answer is None:
            print("No trial number entered. Exiting.")
            sys.exit(0)
        answer = answer.strip()
        if not answer.isdigit() or int(answer) < 1:
            print("Please enter a positive integer.")
            continue
        return int(answer)


# ─────────────────────────────────────────────
# HELPER: Check and ensure scope is stopped
# ─────────────────────────────────────────────

def ensure_stopped(scope: DS1054Z) -> None:
    """
    Checks the scope's run state and stops it only if running.
    Prints the current state so the user knows what happened.

    The DS1054Z reports run state via :TRIG:STAT?
    Possible values: TD, WAIT, RUN, AUTO, STOP
    """
    state = scope.query(":TRIG:STAT?").strip().upper()
    print(f"  Trigger state: {state}")

    if state == "STOP":
        print(f"  ✅ Scope already stopped — proceeding with capture.")
    else:
        print(f"  ⏹  Stopping scope...", end="", flush=True)
        scope.stop()
        time.sleep(0.5)
        state = scope.query(":TRIG:STAT?").strip().upper()
        print(f" done. State now: {state}")


# ─────────────────────────────────────────────
# HELPER: Read one channel RAW
# ─────────────────────────────────────────────

def read_channel(scope: DS1054Z,
                 channel: str) -> tuple[np.ndarray, np.ndarray, dict]:
    """
    Reads full RAW waveform (6M pts) for one channel via LAN.
    Returns (raw_counts, time, preamble).
    """
    print(f"\n{'─'*54}")
    print(f"  Channel : {channel}")
    print(f"  Reading 6M pts via LAN...", end="", flush=True)

    t_start = time.time()
    samples = scope.get_waveform_samples(channel, mode="RAW")
    elapsed = time.time() - t_start

    if samples is None or len(samples) == 0:
        raise RuntimeError(
            f"No samples returned for {channel}. "
            f"Is the channel active and scope stopped?"
        )

    print(f" {len(samples):,} pts in {elapsed:.1f}s")

    scope.write(f":WAV:SOUR {channel}")
    pre = parse_preamble(scope.query(":WAV:PRE?"))

    # Reverse-engineer raw uint8 counts from calibrated floats
    voltage    = np.array(samples, dtype=np.float64)
    raw_counts = np.round(
        voltage / pre["yincrement"]
        + pre["yreference"]
        + pre["yorigin"]
    ).astype(np.uint8)

    n_points = len(raw_counts)
    t        = build_time_axis(
        n_points,
        pre["xincrement"],
        pre["xorigin"],
        pre["xreference"],
    )

    # Round-trip verification
    v_check = counts_to_voltage(
        raw_counts,
        pre["yincrement"],
        pre["yreference"],
        pre["yorigin"],
    )
    max_err = np.max(np.abs(v_check - voltage))

    print(f"  Fs      : {1/pre['xincrement']/1e6:.1f} MSa/s")
    print(f"  Yinc    : {pre['yincrement']*1e3:.4f} mV/count")
    print(f"  Vmin    : {voltage.min():.4f} V  "
          f"Vmax: {voltage.max():.4f} V")
    print(f"  ADC     : min={raw_counts.min()}  "
          f"max={raw_counts.max()}")
    print(f"  RT err  : {max_err*1e6:.2f} µV  "
          f"{'✅' if max_err < 1e-4 else '⚠️'}")

    return raw_counts, t, pre


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    import socket
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

    args = parse_args()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Connect (before prompts, so a missing scope fails fast) ──────────
    print(f"Connecting to DS1054Z at {SCOPE_IP} via LAN/VXI-11...")

    # Port 80 (HTTP web interface) is a reliable TCP reachability probe.
    try:
        with socket.create_connection((SCOPE_IP, 80), timeout=3.0):
            pass
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        print(f"\n❌ Scope not reachable at {SCOPE_IP}: {e}")
        print("   Check that the scope is powered on and connected, then try again.")
        sys.exit(1)

    # VXI-11 connection can still hang if the instrument server is slow;
    # wrap it in a thread so we can enforce a timeout.
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            scope = ex.submit(DS1054Z, SCOPE_IP).result(timeout=8.0)
    except FuturesTimeout:
        print(f"\n❌ Connection to {SCOPE_IP} timed out. Try again.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Could not connect: {e}")
        sys.exit(1)

    idn = scope.idn
    print(f"✅ Connected: {idn}\n")

    # ── Metadata prompts ──────────────────────
    previous_meta = load_previous_metadata()
    default_title = previous_meta.get("experiment_title", "")

    experiment_title = args.experiment.strip() if args.experiment else ask_experiment_title(default_title)
    exp_dir = experiment_dir_for_title(experiment_title)
    exp_defaults = load_experiment_profile(EXPERIMENTS_DIR, experiment_title) or previous_meta

    manifest_defaults: dict[str, str] = {}
    if args.experiment and args.trial is not None:
        existing_layout = build_trial_paths(EXPERIMENTS_DIR, experiment_title, int(args.trial), create=False)
        existing_manifest = load_trial_manifest(existing_layout["trial_manifest_path"])
        if isinstance(existing_manifest.get("experiment_profile"), dict):
            manifest_defaults = {
                str(k): str(v)
                for k, v in existing_manifest["experiment_profile"].items()
            }

    if manifest_defaults:
        current_meta = dict(manifest_defaults)
    elif args.experiment and args.trial is not None and exp_defaults:
        current_meta = dict(exp_defaults)
    else:
        current_meta = prompt_experiment_profile(experiment_title, exp_defaults)

    current_meta["experiment_title"] = experiment_title
    current_meta.update(
        resolve_scope_channel_labels(
            current_meta,
            prompt_for_missing=not (args.experiment and args.trial is not None),
        )
    )
    experiment_profile_path = save_experiment_profile(EXPERIMENTS_DIR, experiment_title, current_meta)

    existing_trials = existing_trial_numbers(exp_dir)
    default_trial = max(existing_trials) + 1 if existing_trials else 1
    trial_number = int(args.trial) if args.trial is not None else ask_trial_number(exp_dir, default_trial)

    layout = build_trial_paths(EXPERIMENTS_DIR, experiment_title, trial_number, create=True)
    trial_dir = layout["trial_dir"]
    micro_scope_dir = layout["micro_scope_dir"]
    trial_manifest_path = layout["trial_manifest_path"]
    capture_dir = next_capture_dir(micro_scope_dir)
    capture_dir.mkdir(parents=True, exist_ok=True)

    hdf5_path = capture_dir / TRIAL_HDF5_NAME
    png_path = capture_dir / TRIAL_PNG_NAME
    screen_path = capture_dir / TRIAL_SCREEN_NAME
    trial_meta_path = capture_dir / TRIAL_META_NAME

    # ── Acquisition state ─────────────────────
    mdep = scope.query(":ACQ:MDEP?").strip()
    srat = scope.query(":ACQ:SRAT?").strip()
    atyp = scope.query(":ACQ:TYPE?").strip()
    print(f"  Memory depth : {int(float(mdep)):,} pts")
    print(f"  Sample rate  : {float(srat)/1e6:.1f} MSa/s")
    print(f"  ACQ type     : {atyp}")

    if atyp.upper() != "NORM":
        print(f"  ⚠️  Setting ACQ:TYPE to NORM for RAW capture")
        scope.write(":ACQ:TYPE NORM")
        time.sleep(0.2)

    # ── Screen capture (before stop) ──────────
    print()
    screen_path = save_screen(scope, screen_path)

    # ── Ensure scope is stopped ───────────────
    print()
    ensure_stopped(scope)

    # ── Read all channels ─────────────────────
    all_raw  = {}
    all_time = {}
    all_pre  = {}

    for ch in CHANNELS:
        raw, t, pre = read_channel(scope, ch)
        all_raw[ch]  = raw
        all_time[ch] = t
        all_pre[ch]  = pre

    print(f"\n✅ All channels read.")

    # ── Save HDF5 ─────────────────────────────
    print(f"\nSaving HDF5 → {hdf5_path} ...")
    with h5py.File(hdf5_path, "w") as f:
        f.attrs["instrument"]        = idn
        f.attrs["capture_time"]      = timestamp
        f.attrs["interface"]         = "LAN/VXI-11"
        f.attrs["wav_mode"]          = "RAW"
        f.attrs["wav_format"]        = "BYTE"
        f.attrs["acq_type"]          = "NORM"
        f.attrs["memory_depth"]      = int(float(mdep))
        f.attrs["sample_rate"]       = float(srat)
        f.attrs["screen_png"]        = str(screen_path) if screen_path else ""
        f.attrs["voltage_formula"]   = "V = (raw - yreference - yorigin) * yincrement"
        f.attrs["experiment_title"]  = current_meta.get("experiment_title", "")
        f.attrs["operator"]          = current_meta.get("operator", "")
        f.attrs["description"]       = current_meta.get("description", "")
        f.attrs["channel_labels"]    = ";".join(
            f"{ch}={current_meta.get('channel_label_' + ch, '')}"
            for ch in CHANNELS
        )

        for ch in CHANNELS:
            grp = f.create_group(ch)
            pre = all_pre[ch]

            ds = grp.create_dataset(
                "raw",
                data=all_raw[ch],
                dtype=np.uint8,
                compression="gzip",
                compression_opts=6,
            )
            ds.attrs["yincrement"]  = pre["yincrement"]
            ds.attrs["yorigin"]     = pre["yorigin"]
            ds.attrs["yreference"]  = pre["yreference"]
            ds.attrs["xincrement"]  = pre["xincrement"]
            ds.attrs["xorigin"]     = pre["xorigin"]
            ds.attrs["xreference"]  = pre["xreference"]
            ds.attrs["sample_rate"] = 1.0 / pre["xincrement"]
            ds.attrs["n_points"]    = len(all_raw[ch])
            ds.attrs["label"]       = current_meta.get(
                f"channel_label_{ch}", CHANNEL_LABELS[ch]
            )
            ds.attrs["format"]      = pre["format"]
            ds.attrs["type"]        = pre["type"]

    print(f"✅ HDF5 saved → {hdf5_path}")

    trial_meta = {
        "trial_number": trial_number,
        "scope_capture_id": capture_dir.name,
        "capture_time": timestamp,
        "experiment_title": current_meta.get("experiment_title", ""),
        "description": current_meta.get("description", ""),
        "operator": current_meta.get("operator", ""),
        "hdf5_path": str(hdf5_path),
        "screen_png": str(screen_path) if screen_path else "",
        "experiment_profile": current_meta,
        "experiment_profile_path": str(experiment_profile_path),
        "layout": {
            "experiment_dir": str(exp_dir),
            "trial_dir": str(trial_dir),
            "micro_scope_dir": str(micro_scope_dir),
            "capture_dir": str(capture_dir),
        },
        **{
            k: v
            for k, v in current_meta.items()
            if k not in {"experiment_title", "description", "operator"}
        },
    }
    trial_meta_path.write_text(
        json.dumps(trial_meta, indent=2),
        encoding="utf-8",
    )
    print(f"✅ Trial metadata saved → {trial_meta_path}")

    manifest = load_trial_manifest(trial_manifest_path)
    streams = manifest.get("streams") if isinstance(manifest.get("streams"), dict) else {}
    streams["rigol"] = {
        "requested": True,
        "enabled": True,
        "status": "completed",
        "files": {
            "hdf5": str(hdf5_path),
            "png": str(png_path),
            "screen_png": str(screen_path) if screen_path else "",
            "metadata": str(trial_meta_path),
        },
        "scope_capture_id": capture_dir.name,
    }

    requested_streams = set(manifest.get("requested_streams", []))
    completed_streams = set(manifest.get("completed_streams", []))
    skipped_streams = set(manifest.get("skipped_streams", []))
    requested_streams.add("rigol")
    completed_streams.add("rigol")
    skipped_streams.discard("rigol")

    manifest.update(
        {
            "experiment_title": experiment_title,
            "trial_number": trial_number,
            "capture_time": timestamp,
            "experiment_profile": current_meta,
            "experiment_profile_path": str(experiment_profile_path),
            "requested_streams": sorted(requested_streams),
            "completed_streams": sorted(completed_streams),
            "skipped_streams": sorted(skipped_streams),
            "streams": streams,
        }
    )
    save_trial_manifest(trial_manifest_path, manifest)
    print(f"✅ Trial manifest saved → {trial_manifest_path}")

    # ── Compute voltages for plot ─────────────
    voltages = {
        ch: counts_to_voltage(
            all_raw[ch],
            all_pre[ch]["yincrement"],
            all_pre[ch]["yreference"],
            all_pre[ch]["yorigin"],
        )
        for ch in CHANNELS
    }

    # ── Plot ──────────────────────────────────
    print(f"\nRendering plot...")
    title_line1 = (
        f"{current_meta.get('experiment_title', 'Rigol DS1054Z — RAW Capture')}  "
        "[6M pts × 4 ch @ 250 MSa/s]"
    )
    title_line2 = (
        f"{current_meta.get('description', timestamp)}"
        if current_meta.get('description') else timestamp
    )

    make_scope_plot(
        time_axes   = all_time,
        voltages    = voltages,
        title_line1 = title_line1,
        title_line2 = title_line2,
        channel_labels = {
            ch: current_meta.get(f"channel_label_{ch}", CHANNEL_LABELS[ch])
            for ch in CHANNELS
        },
        png_path    = png_path,
    )

    print(f"\n🎉 Done!")
    print(f"   📁 {hdf5_path}")
    print(f"   🖼️  {png_path}")
    if screen_path:
        print(f"   📷  {screen_path}")


if __name__ == "__main__":
    main()