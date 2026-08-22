# load_rigol_capture.py
"""
Load and interactively plot a previously captured Rigol DS1054Z waveform.

Selects an HDF5 capture using questionary, then loads all 4 channels
and provides the same interactive scope-style plot as rigol_capture.py.

Imports all shared logic from rigol_common.py — updating that file
updates both this script and rigol_capture.py simultaneously.

Requirements:
    pip install h5py matplotlib numpy questionary
"""

import h5py
import json
import numpy as np
from pathlib import Path
import questionary

from rigol.common import (
    CHANNELS,
    counts_to_voltage,
    build_time_axis,
    make_scope_plot,
)

EXPERIMENTS_DIR = Path("experiments")
TRIAL_META_NAME = "scope_capture_meta.json"


# ─────────────────────────────────────────────
# LOAD HDF5 CAPTURE
# ─────────────────────────────────────────────

def _decode_attr(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def parse_channel_labels(label_string: str) -> dict[str, str]:
    labels = {}
    if not label_string:
        return labels

    for item in label_string.split(";"):
        if "=" in item:
            ch, label = item.split("=", 1)
            labels[ch] = label
    return labels


def load_capture(filename: Path) -> tuple[dict, dict, dict, dict]:
    """
    Load all channels from an HDF5 Rigol capture.

    Returns
    -------
    raw_counts : dict  ch → uint8 array
    time_axes  : dict  ch → float64 seconds array
    voltages   : dict  ch → float64 volts array
    metadata   : dict  file-level attributes
    """
    raw_counts = {}
    time_axes  = {}
    voltages   = {}
    metadata   = {}

    print(f"\nLoading {filename}...")

    with h5py.File(filename, "r") as f:

        for key, value in f.attrs.items():
            metadata[key] = str(value)

        for ch in CHANNELS:
            ds  = f[f"{ch}/raw"]
            raw = ds[:]

            yinc = ds.attrs["yincrement"]
            yref = ds.attrs["yreference"]
            yorg = ds.attrs["yorigin"]
            xinc = ds.attrs["xincrement"]
            xorg = ds.attrs["xorigin"]
            xref = ds.attrs["xreference"]

            raw_counts[ch] = raw
            voltages[ch]   = counts_to_voltage(raw, yinc, yref, yorg)
            time_axes[ch]  = build_time_axis(len(raw), xinc, xorg, xref)

    return raw_counts, time_axes, voltages, metadata


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():

    # ── Find all captures under experiments/ ──
    if not EXPERIMENTS_DIR.exists():
        print(f"No '{EXPERIMENTS_DIR}' directory found. Run rigol_capture.py first.")
        return

    h5_files = sorted(
        EXPERIMENTS_DIR.rglob("rigol_capture.h5"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    if not h5_files:
        print(f"No Rigol capture files found under {EXPERIMENTS_DIR}/")
        return

    # ── Group by experiment (top-level folder under experiments/) ────────
    # Path structure:
    #   experiments/<exp>/trials/trial_NNNN/
    #       micro_scope/capture_NNN/rigol_capture.h5
    def experiment_name(h5: Path) -> str:
        try:
            return h5.relative_to(EXPERIMENTS_DIR).parts[0]
        except ValueError:
            return "unknown"

    experiments = sorted({experiment_name(f) for f in h5_files})

    if len(experiments) > 1:
        chosen_exp = questionary.select(
            "Select experiment:",
            choices=experiments,
        ).ask()
        if chosen_exp is None:
            return
        h5_files = [f for f in h5_files if experiment_name(f) == chosen_exp]
    else:
        chosen_exp = experiments[0]

    # ── Build labelled choices for the selected experiment ────────────────
    def capture_label(h5: Path) -> str:
        parts = h5.relative_to(EXPERIMENTS_DIR).parts
        # parts: exp / trials / <trial> / micro_scope / <capture> / rigol_capture.h5
        trial_part   = parts[2] if len(parts) > 2 else "?"
        capture_part = parts[4] if len(parts) > 4 else "?"

        meta_path = h5.parent / TRIAL_META_NAME
        description = ""
        capture_time = ""
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
                description = meta.get("description", "")
                capture_time = meta.get("capture_time", "")
            except Exception:
                pass

        label = f"{trial_part} / {capture_part}"
        if capture_time:
            label += f"  {capture_time}"
        if description:
            label += f"  — {description}"
        return label

    choices = {capture_label(f): f for f in h5_files}

    chosen_label = questionary.select(
        f"Select capture  ({chosen_exp}):",
        choices=list(choices.keys()),
    ).ask()

    if chosen_label is None:
        return

    filename = choices[chosen_label]

    # ── Load ──────────────────────────────────
    raw_counts, time_axes, voltages, metadata = load_capture(filename)

    # ── Print summary ─────────────────────────
    print(f"\nLoaded: {filename.relative_to(EXPERIMENTS_DIR)}")
    for ch in CHANNELS:
        raw  = raw_counts[ch]
        v    = voltages[ch]
        t    = time_axes[ch]
        xinc = t[1] - t[0] if len(t) > 1 else 0
        print(
            f"  {ch}: {len(raw):,} samples  "
            f"{1/xinc/1e6:.1f} MSa/s  "
            f"{v.min():.4f} V → {v.max():.4f} V"
        )

    # ── Check for companion screen PNG ────────
    screen_png = metadata.get("screen_png", None)
    if screen_png and Path(screen_png).exists():
        print(f"\n  📷 Scope screen: {screen_png}")

    # ── Build plot titles from metadata ───────
    exp_title    = metadata.get("experiment_title", chosen_exp)
    description  = metadata.get("description", "")
    capture_time = metadata.get("capture_time", filename.stem)
    channel_labels = parse_channel_labels(metadata.get("channel_labels", ""))

    title_line1 = f"{exp_title}  [{filename.parent.name}]"
    title_line2 = description if description else str(capture_time)

    # ── Plot ──────────────────────────────────
    print("\nOpening interactive plot...")
    make_scope_plot(
        time_axes   = time_axes,
        voltages    = voltages,
        title_line1 = title_line1,
        title_line2 = title_line2,
        channel_labels = channel_labels,
        png_path    = None,
    )


if __name__ == "__main__":
    main()