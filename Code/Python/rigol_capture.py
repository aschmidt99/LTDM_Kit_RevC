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
from rigol_common import (
    CHANNELS, CHANNEL_LABELS,
    counts_to_voltage, build_time_axis,
    make_scope_plot,
)
import getpass
import json
import re
import shutil
import numpy as np
import h5py
from datetime import datetime
from pathlib import Path
from rigol_screen import save_screen
import questionary
import sys
import time

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

from rigol_common import SCOPE_IP
OUTPUT_HDF5 = "rigol_capture.h5"
OUTPUT_PNG  = "rigol_capture.png"
SCREEN_PNG  = "rigol_screen.png"
EXPERIMENTS_DIR = Path("experiments")
EXPERIMENT_META_NAME = "experiment.json"
TRIAL_META_NAME = "trial_metadata.json"
TRIAL_DIR_PREFIX = "trial_"
TRIAL_HDF5_NAME = "rigol_capture.h5"
TRIAL_PNG_NAME = "rigol_capture.png"
TRIAL_SCREEN_NAME = "rigol_screen.png"


# ─────────────────────────────────────────────
# HELPER: Experiment metadata and folder utilities
# ─────────────────────────────────────────────

def safe_name(value: str) -> str:
    value = value.strip()
    value = re.sub(r"[^A-Za-z0-9 _-]", "", value)
    value = re.sub(r"[\s]+", "_", value)
    return value or "untitled_experiment"


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


def load_experiment_metadata(exp_dir: Path) -> dict[str, str]:
    meta_file = exp_dir / EXPERIMENT_META_NAME
    if not meta_file.exists():
        return {}

    try:
        return json.loads(meta_file.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_experiment_metadata(exp_dir: Path, meta: dict[str, str]) -> None:
    exp_dir.mkdir(parents=True, exist_ok=True)
    meta_file = exp_dir / EXPERIMENT_META_NAME
    meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")


def existing_trial_numbers(exp_dir: Path) -> list[int]:
    if not exp_dir.exists():
        return []
    trials = []
    for child in exp_dir.iterdir():
        if child.is_dir() and child.name.startswith(TRIAL_DIR_PREFIX):
            match = re.match(rf"^{TRIAL_DIR_PREFIX}(\d+)$", child.name)
            if match:
                trials.append(int(match.group(1)))
    return sorted(trials)


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


def ask_experiment_metadata(defaults: dict[str, str]) -> dict[str, str]:
    meta = {}

    meta["operator"] = questionary.text(
        "Operator name:",
        default=defaults.get("operator", getpass.getuser()),
    ).ask() or defaults.get("operator", getpass.getuser())

    meta["description"] = questionary.text(
        "Short description / notes:",
        default=defaults.get("description", ""),
    ).ask() or defaults.get("description", "")

    meta["string_material"] = questionary.text(
        "String material:",
        default=defaults.get("string_material", ""),
    ).ask() or defaults.get("string_material", "")

    meta["speaking_length_cm"] = questionary.text(
        "Speaking length of string (cm):",
        default=defaults.get("speaking_length_cm", ""),
    ).ask() or defaults.get("speaking_length_cm", "")

    meta["string_gauge_mm"] = questionary.text(
        "String gauge (mm):",
        default=defaults.get("string_gauge_mm", ""),
    ).ask() or defaults.get("string_gauge_mm", "")

    meta["string_resistance_ohm"] = questionary.text(
        "String resistance (Ω):",
        default=defaults.get("string_resistance_ohm", ""),
    ).ask() or defaults.get("string_resistance_ohm", "")

    meta["string_fundamental_hz"] = questionary.text(
        "String fundamental frequency (Hz):",
        default=defaults.get("string_fundamental_hz", ""),
    ).ask() or defaults.get("string_fundamental_hz", "")

    meta["magnet_grade"] = questionary.text(
        "Magnet grade (e.g. N35):",
        default=defaults.get("magnet_grade", ""),
    ).ask() or defaults.get("magnet_grade", "")

    meta["magnet_pull_strength_kg"] = questionary.text(
        "Magnet pull strength (kg):",
        default=defaults.get("magnet_pull_strength_kg", ""),
    ).ask() or defaults.get("magnet_pull_strength_kg", "")

    meta["magnet_position_cm"] = questionary.text(
        "Magnet position along string (cm):",
        default=defaults.get("magnet_position_cm", ""),
    ).ask() or defaults.get("magnet_position_cm", "")

    meta["magnet_distance_mm"] = questionary.text(
        "Magnet distance from string center (mm):",
        default=defaults.get("magnet_distance_mm", ""),
    ).ask() or defaults.get("magnet_distance_mm", "")

    meta["magnet_dimensions_mm"] = questionary.text(
        "Magnet dimensions (mm x mm x mm):",
        default=defaults.get("magnet_dimensions_mm", ""),
    ).ask() or defaults.get("magnet_dimensions_mm", "")

    meta["magnets_in_stack"] = questionary.text(
        "Number of magnets in stack:",
        default=defaults.get("magnets_in_stack", ""),
    ).ask() or defaults.get("magnets_in_stack", "")

    for ch in CHANNELS:
        meta[f"channel_label_{ch}"] = questionary.text(
            f"Channel {ch} label:",
            default=defaults.get(f"channel_label_{ch}", ""),
        ).ask() or defaults.get(f"channel_label_{ch}", "")

    return {k: str(v).strip() for k, v in meta.items()}


def ask_trial_number(exp_dir: Path, default_trial: int) -> int:
    existing = set(existing_trial_numbers(exp_dir))
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
        trial = int(answer)
        if trial in existing and answer != default_str:
            overwrite = questionary.confirm(
                f"Trial {trial} already exists. Overwrite previous data?",
                default=False,
            ).ask()
            if not overwrite:
                continue
        return trial


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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    previous_meta = load_previous_metadata()
    default_title = previous_meta.get("experiment_title", "")

    experiment_title = ask_experiment_title(default_title)
    exp_dir = experiment_dir_for_title(experiment_title)
    exp_defaults = load_experiment_metadata(exp_dir) or previous_meta

    current_meta = ask_experiment_metadata(exp_defaults)
    current_meta["experiment_title"] = experiment_title
    save_experiment_metadata(exp_dir, current_meta)

    existing_trials = existing_trial_numbers(exp_dir)
    default_trial = max(existing_trials) + 1 if existing_trials else 1
    trial_number = ask_trial_number(exp_dir, default_trial)

    trial_dir = exp_dir / f"{TRIAL_DIR_PREFIX}{trial_number}"
    if trial_dir.exists():
        shutil.rmtree(trial_dir)
    trial_dir.mkdir(parents=True, exist_ok=True)

    hdf5_path = trial_dir / TRIAL_HDF5_NAME
    png_path = trial_dir / TRIAL_PNG_NAME
    screen_path = trial_dir / TRIAL_SCREEN_NAME
    trial_meta_path = trial_dir / TRIAL_META_NAME

    # ── Connect ───────────────────────────────
    print(f"Connecting to DS1054Z at {SCOPE_IP} via LAN/VXI-11...")
    try:
        scope = DS1054Z(SCOPE_IP)
    except Exception as e:
        print(f"\n❌ Could not connect: {e}")
        sys.exit(1)

    idn = scope.idn
    print(f"✅ Connected: {idn}\n")

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
        "capture_time": timestamp,
        "experiment_title": current_meta.get("experiment_title", ""),
        "description": current_meta.get("description", ""),
        "operator": current_meta.get("operator", ""),
        "hdf5_path": str(hdf5_path),
        "screen_png": str(screen_path) if screen_path else "",
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
        png_path    = png_path,
    )

    print(f"\n🎉 Done!")
    print(f"   📁 {hdf5_path}")
    print(f"   🖼️  {png_path}")
    if screen_path:
        print(f"   📷  {screen_path}")


if __name__ == "__main__":
    main()