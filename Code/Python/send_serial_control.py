"""Send a test LTDM serial-control frame every half second."""

from __future__ import annotations

import argparse
import random
import time


START_MARKER = 255
END_MARKER = 254
UPDATE_INTERVAL_SECONDS = 0.5


def build_frame(ch1_target_rms: int, ch2_target_rms: int) -> bytes:
    """Build the 37-byte frame expected by serialctrl.cpp."""
    payload = [
        1,
        63,
        ch1_target_rms,
        63,
        63,
        63,
        ch2_target_rms,
        63,
        63,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        1,
        1,
        1,
        1,
        0,
        0,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    ]
    if len(payload) != 35:
        raise AssertionError(f"Expected 35 payload bytes, got {len(payload)}")
    if any(not 0 <= value <= 127 for value in payload):
        raise ValueError("Payload values must be between 0 and 127")
    return bytes([START_MARKER, *payload, END_MARKER])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send randomized Channel 1/2 target-RMS values to the LTDM Teensy."
    )
    parser.add_argument("--port", required=True, help="Teensy serial port, e.g. /dev/cu.usbmodem199934501")
    parser.add_argument(
        "--interval",
        type=float,
        default=UPDATE_INTERVAL_SECONDS,
        help="Seconds between frames (default: 0.5)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.interval <= 0:
        raise SystemExit("--interval must be greater than zero")

    try:
        import serial
    except ImportError as exc:
        raise SystemExit("pyserial is required; install it with: python3 -m pip install pyserial") from exc

    print(f"Opening {args.port} at 115200 baud. Press Ctrl-C to stop.")
    try:
        with serial.Serial(
            args.port,
            115200,
            timeout=1,
            dsrdtr=False,
            rtscts=False,
            xonxoff=False,
        ) as connection:
            while True:
                ch1_target_rms = random.randint(0, 127)
                ch2_target_rms = random.randint(0, 127)
                frame = build_frame(ch1_target_rms, ch2_target_rms)
                connection.write(frame)
                connection.flush()
                print(
                    f"Ch1 target RMS={ch1_target_rms:3d}  "
                    f"Ch2 target RMS={ch2_target_rms:3d}"
                )
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    except serial.SerialException as exc:
        raise SystemExit(f"Could not use serial port {args.port}: {exc}") from exc


if __name__ == "__main__":
    main()