import argparse
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt

SAMPLE_RATE_HZ = 20000
CHANNELS = 2


def parse_args():
    parser = argparse.ArgumentParser(description="Plot Teensy captured stream data.")
    parser.add_argument("file", help="Path to teensy_stream.bin")
    parser.add_argument("--duration", type=float, default=None, help="Seconds of data to plot")
    parser.add_argument("--channel", type=int, choices=[1, 2], default=None, help="Plot only one channel")
    parser.add_argument("--start", type=float, default=0.0, help="Start time in seconds")
    return parser.parse_args()


def load_stream(path: Path):
    raw = path.read_bytes()
    data = np.frombuffer(raw, dtype=np.int16)
    if len(data) % CHANNELS != 0:
        raise ValueError(f"Binary capture length not divisible by {CHANNELS}: {len(data)}")
    data = data.reshape(-1, CHANNELS)
    return data


def plot_stream(data: np.ndarray, args):
    n_samples = data.shape[0]
    t = np.arange(n_samples) / SAMPLE_RATE_HZ

    start_idx = int(args.start * SAMPLE_RATE_HZ)
    if start_idx < 0:
        start_idx = 0
    if args.duration is not None:
        end_idx = start_idx + int(args.duration * SAMPLE_RATE_HZ)
    else:
        end_idx = n_samples
    end_idx = min(end_idx, n_samples)

    t = t[start_idx:end_idx]
    data = data[start_idx:end_idx]

    plt.figure(figsize=(14, 6))
    if args.channel is None or args.channel == 1:
        plt.plot(t, data[:, 0], label="Channel 1")
    if args.channel is None or args.channel == 2:
        plt.plot(t, data[:, 1], label="Channel 2")
    plt.xlabel("Time (s)")
    plt.ylabel("Signed int16 sample")
    plt.title(f"Teensy stream plot: {path.name}")
    plt.grid(True)
    plt.legend()
    plt.tight_layout()
    plt.show()


def main():
    args = parse_args()
    global path
    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"File not found: {path}")

    data = load_stream(path)
    plot_stream(data, args)


if __name__ == "__main__":
    main()
