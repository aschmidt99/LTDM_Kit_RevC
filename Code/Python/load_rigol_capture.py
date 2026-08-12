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
import numpy as np
from pathlib import Path
import questionary

from rigol_common import (
    CHANNELS,
    counts_to_voltage,
    build_time_axis,
    make_scope_plot,
)


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

    # ── Find captures ─────────────────────────
    files = sorted(
        Path(".").rglob("rigol_capture.h5"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    if not files:
        print("No Rigol capture files found in the current directory.")
        return

    # ── Select capture ────────────────────────
    choices = [str(f.relative_to(Path.cwd())) for f in files]
    chosen = questionary.select(
        "Select a capture:",
        choices=choices,
    ).ask()

    if chosen is None:
        print("No file selected.")
        return

    filename = Path(chosen)

    # ── Load ──────────────────────────────────
    raw_counts, time_axes, voltages, metadata = load_capture(filename)

    # ── Print summary ─────────────────────────
    print(f"\nLoaded: {filename.name}")
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

    # ── Plot ──────────────────────────────────
    print("\nOpening interactive plot...")
    capture_time = metadata.get("capture_time", filename.stem)

    make_scope_plot(
        time_axes   = time_axes,
        voltages    = voltages,
        title_line1 = f"Rigol DS1054Z — RAW Capture  [{filename.name}]",
        title_line2 = str(capture_time),
        png_path    = None,    # no PNG save on load — view only
    )


if __name__ == "__main__":
    main()