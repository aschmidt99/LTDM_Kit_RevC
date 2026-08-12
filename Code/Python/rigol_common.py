# rigol_common.py
"""
Shared constants, helpers, and plotting for Rigol DS1054Z capture tools.

Imported by both rigol_capture.py and load_rigol_capture.py.
Update this file to affect both scripts simultaneously.
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# ─────────────────────────────────────────────
# SHARED CONFIGURATION
# ─────────────────────────────────────────────
SCOPE_IP = "169.254.123.183"
from rigol_screen import save_screen

CHANNELS = ["CHAN1", "CHAN2", "CHAN3", "CHAN4"]

# Render points for initial decimated plot (2× Retina pixel width)
RENDER_POINTS = 5_600

# Threshold: show per-point markers when fewer than this
# many raw points are visible in the current zoom window
MARKER_THRESHOLD = 2_000

CHANNEL_COLORS = {
    "CHAN1": "#F5C400",
    "CHAN2": "#00B4B4",
    "CHAN3": "#FF00FF",
    "CHAN4": "#0050FF",
}
CHANNEL_LABELS = {
    "CHAN1": "CH1",
    "CHAN2": "CH2",
    "CHAN3": "CH3",
    "CHAN4": "CH4",
}


# ─────────────────────────────────────────────
# HELPER: Raw counts → calibrated voltage
# ─────────────────────────────────────────────

def counts_to_voltage(raw: np.ndarray,
                      yincrement: float,
                      yreference: float,
                      yorigin: float) -> np.ndarray:
    """
    Applies the Rigol voltage scaling formula:
        V = (raw - yreference - yorigin) * yincrement

    Parameters
    ----------
    raw        : uint8 ADC count array
    yincrement : volts per ADC count
    yreference : ADC count corresponding to 0V
    yorigin    : vertical offset in ADC counts

    Returns
    -------
    float64 voltage array
    """
    return (raw.astype(np.float64)
            - yreference
            - yorigin) * yincrement


# ─────────────────────────────────────────────
# HELPER: Build time axis
# ─────────────────────────────────────────────

def build_time_axis(n_points: int,
                    xincrement: float,
                    xorigin: float,
                    xreference: float) -> np.ndarray:
    """
    Builds the time axis:
        t[i] = xorigin + (i - xreference) * xincrement

    Parameters
    ----------
    n_points   : number of samples
    xincrement : seconds per sample
    xorigin    : time of first sample (seconds)
    xreference : reference index for time zero

    Returns
    -------
    float64 time array in seconds
    """
    i = np.arange(n_points, dtype=np.float64)
    return xorigin + (i - xreference) * xincrement


# ─────────────────────────────────────────────
# HELPER: Min/max envelope decimation
# ─────────────────────────────────────────────

def minmax_decimate(t: np.ndarray, y: np.ndarray,
                    n_out: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Decimates (t, y) to n_out points using min/max envelope.
    For each bin, keeps both the minimum AND maximum sample,
    preserving the full visual envelope at any zoom level.
    Identical to how the DS1054Z renders its own display.

    Parameters
    ----------
    t     : time array
    y     : voltage array
    n_out : target output length (must be even)

    Returns
    -------
    t_out, y_out : decimated arrays
    """
    n_in      = len(y)
    n_bins    = n_out // 2
    bin_size  = n_in // n_bins
    n_trimmed = bin_size * n_bins

    y_b = y[:n_trimmed].reshape(n_bins, bin_size)
    t_b = t[:n_trimmed].reshape(n_bins, bin_size)

    min_idx    = np.argmin(y_b, axis=1)
    max_idx    = np.argmax(y_b, axis=1)
    bin_offset = np.arange(n_bins) * bin_size
    min_flat   = bin_offset + min_idx
    max_flat   = bin_offset + max_idx

    t_out = np.empty(n_out)
    y_out = np.empty(n_out)

    for i in range(n_bins):
        mi, mx = min_flat[i], max_flat[i]
        if t[mi] <= t[mx]:
            t_out[2*i],   y_out[2*i]   = t[mi], y[mi]
            t_out[2*i+1], y_out[2*i+1] = t[mx], y[mx]
        else:
            t_out[2*i],   y_out[2*i]   = t[mx], y[mx]
            t_out[2*i+1], y_out[2*i+1] = t[mi], y[mi]

    return t_out, y_out


# ─────────────────────────────────────────────
# HELPER: Scope-style plot with zoom callback
# ─────────────────────────────────────────────

def make_scope_plot(time_axes: dict,
                    voltages: dict,
                    title_line1: str,
                    title_line2: str,
                    png_path: str | None = None) -> None:
    """
    Plots all 4 channels with min/max envelope decimation.

    Zoom/pan callback re-decimates the visible window from the
    full dataset. Dots appear automatically at each real data
    point when the zoom window contains fewer than
    MARKER_THRESHOLD points — making quantization visible
    without cluttering the full-zoom view.

    Parameters
    ----------
    time_axes   : dict  ch → float64 time array (seconds)
    voltages    : dict  ch → float64 voltage array
    title_line1 : first title line (e.g. capture mode/source)
    title_line2 : second title line (e.g. timestamp/filename)
    png_path    : if provided, saves PNG before showing
    """
    fig, ax = plt.subplots(figsize=(14, 6))
    fig.patch.set_facecolor("#1a1a1a")
    ax.set_facecolor("#1a1a1a")

    lines = {}

    # ── Initial full-window decimated plot ────
    for ch in CHANNELS:
        t_ms = time_axes[ch] * 1e3
        v    = voltages[ch]

        if len(t_ms) > RENDER_POINTS:
            t_d, v_d = minmax_decimate(t_ms, v, RENDER_POINTS)
        else:
            t_d, v_d = t_ms, v

        # Start with no markers — zoom callback adds them
        line, = ax.plot(
            t_d, v_d,
            color=CHANNEL_COLORS[ch],
            linewidth=0.7,
            label=CHANNEL_LABELS[ch],
            alpha=0.92,
            marker="None",
        )
        lines[ch] = line

    # ── Zoom/pan callback ─────────────────────
    def on_xlim_changed(event_ax):
        xmin, xmax = event_ax.get_xlim()

        for ch in CHANNELS:
            t_ms = time_axes[ch] * 1e3
            v    = voltages[ch]
            mask = (t_ms >= xmin) & (t_ms <= xmax)

            if mask.sum() < 2:
                continue

            t_win = t_ms[mask]
            v_win = v[mask]
            n_raw = len(t_win)

            if n_raw <= RENDER_POINTS:
                # Fully zoomed — plot every raw sample
                lines[ch].set_data(t_win, v_win)
            else:
                # Still decimating — use min/max envelope
                n_out = min(RENDER_POINTS, (n_raw // 2) * 2)
                n_out = max(n_out, 4)
                t_d, v_d = minmax_decimate(t_win, v_win, n_out)
                lines[ch].set_data(t_d, v_d)

            # Show dots when zoomed in enough to see
            # individual samples without overlap
            if n_raw <= MARKER_THRESHOLD:
                lines[ch].set_marker(".")
                lines[ch].set_markersize(3.5)
                lines[ch].set_markerfacecolor(CHANNEL_COLORS[ch])
                lines[ch].set_markeredgewidth(0)
            else:
                lines[ch].set_marker("None")

        fig.canvas.draw_idle()

    ax.callbacks.connect("xlim_changed", on_xlim_changed)

    # ── Formatting ────────────────────────────
    ax.set_xlabel("Time (ms)", color="white", fontsize=12)
    ax.set_ylabel("Voltage (V)", color="white", fontsize=12)
    ax.set_title(
        f"{title_line1}\n{title_line2}",
        color="white", fontsize=12
    )
    ax.tick_params(colors="white")
    for spine in ax.spines.values():
        spine.set_edgecolor("#444444")
    ax.grid(True, color="#333333", linestyle="--", linewidth=0.5)
    ax.xaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax.yaxis.set_minor_locator(ticker.AutoMinorLocator(5))
    ax.grid(True, which="minor", color="#2a2a2a",
            linestyle=":", linewidth=0.4)
    ax.legend(loc="upper right", framealpha=0.3, facecolor="#111111",
              edgecolor="#555555", labelcolor="white", fontsize=11)

    plt.tight_layout()

    if png_path:
        plt.savefig(png_path, dpi=200, facecolor=fig.get_facecolor())
        print(f"✅ Plot saved → {png_path}")

    plt.show()