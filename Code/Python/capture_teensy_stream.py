import argparse
import serial
import struct
import time
from pathlib import Path
from datetime import datetime
import json

CMD_ARM = b'A'
CMD_STOP = b'T'
ARM_ACK = b'ARMED'
CAPTURE_MARKER = b'\xAA\x55'

DEFAULT_DURATION_S = 5
SAMPLE_RATE_HZ = 20000
CHANNELS = 2
ARM_ACK_TIMEOUT_S = 1.0
ARM_RETRY_COUNT = 5


def parse_args():
    parser = argparse.ArgumentParser(description="Capture Teensy stream and save as WAV/JSON.")
    parser.add_argument("--port", required=True, help="Serial port for Teensy")
    parser.add_argument("--output-dir", default="experiments", help="Base output directory")
    parser.add_argument("--experiment", default="TeensyCapture", help="Experiment title")
    parser.add_argument("--trial", type=int, default=1, help="Trial number")
    parser.add_argument("--duration", type=int, default=None, help="Capture duration in seconds")
    parser.add_argument("--save-wav", action="store_true", help="Save the captured stream as WAV")
    return parser.parse_args()


def safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in value).strip().replace(" ", "_") or "untitled"


def write_wav(filename: Path, samples: bytes, sample_rate: int, channels: int = 2):
    import wave
    with wave.open(str(filename), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples)


def extract_channels(buffer: bytes, channels: int = 2):
    from array import array
    samples = array('h')
    samples.frombytes(buffer)
    if len(samples) % channels != 0:
        raise ValueError(f"Binary capture length not divisible by {channels}: {len(samples)}")
    channel_bytes = []
    for ch in range(channels):
        channel_data = array('h', samples[ch::channels])
        channel_bytes.append(channel_data.tobytes())
    return channel_bytes, samples


def read_until_marker(ser, marker: bytes, timeout: float | None = 10.0):
    deadline = None if timeout is None else time.time() + timeout
    buffer = bytearray()
    while deadline is None or time.time() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if not chunk:
            continue
        buffer.extend(chunk)
        index = buffer.find(marker)
        if index != -1:
            return True, buffer[index + len(marker):]
        if len(buffer) > len(marker) * 4:
            buffer = buffer[-len(marker) * 4:]
    return False, b''


def prompt_duration(default_seconds: int) -> int:
    raw = input(f"Capture duration in seconds [{default_seconds}]: ").strip()
    if not raw:
        return default_seconds
    try:
        seconds = int(raw)
    except ValueError as exc:
        raise SystemExit("Capture duration must be an integer number of seconds") from exc
    if seconds <= 0 or seconds > 30:
        raise SystemExit("Capture duration must be between 1 and 30 seconds")
    return seconds





def main():
    args = parse_args()
    duration_seconds = args.duration if args.duration is not None else prompt_duration(DEFAULT_DURATION_S)
    exp_dir = Path(args.output_dir) / safe_name(args.experiment)
    trial_dir = exp_dir / f"trial_{args.trial}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "experiment_title": args.experiment,
        "trial_number": args.trial,
        "duration_seconds": duration_seconds,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "channels": CHANNELS,
        "capture_time": datetime.now().isoformat(),
    }

    raw_path = trial_dir / "teensy_stream.bin"
    ch1_raw_path = trial_dir / "teensy_stream_ch1.bin"
    ch2_raw_path = trial_dir / "teensy_stream_ch2.bin"
    wav_path = trial_dir / "teensy_stream.wav"
    ch1_wav_path = trial_dir / "teensy_stream_ch1.wav"
    ch2_wav_path = trial_dir / "teensy_stream_ch2.wav"
    meta_path = trial_dir / "teensy_capture_metadata.json"

    with serial.Serial(args.port, 2000000, timeout=1, dsrdtr=False, rtscts=False, xonxoff=False) as ser:
        time.sleep(0.5)
        ser.reset_input_buffer()
        ser.reset_output_buffer()
        arm_command = CMD_ARM + bytes([duration_seconds])
        attempts = ARM_RETRY_COUNT
        armed = False
        leftover = b''
        for attempt in range(attempts):
            print(f"Arming capture on {args.port} for {duration_seconds} seconds (attempt {attempt+1})")
            ser.write(arm_command)
            ser.flush()
            armed, leftover = read_until_marker(ser, ARM_ACK, timeout=ARM_ACK_TIMEOUT_S)
            if armed:
                break
            time.sleep(0.05)
        if not armed:
            raise SystemExit("Timeout waiting for armed acknowledgement from Teensy")
        print("Teensy armed and debug output paused")

        print("Press LTDM Kit button 8 to start capture")
        ok, leftover = read_until_marker(ser, CAPTURE_MARKER, timeout=None)
        print("Capture start marker received")

        print(f"Capturing {duration_seconds} seconds of data...")
        total_samples = duration_seconds * SAMPLE_RATE_HZ
        total_bytes = total_samples * CHANNELS * 2
        buffer = bytearray(leftover)

        while len(buffer) < total_bytes:
            data = ser.read(total_bytes - len(buffer))
            if not data:
                continue
            buffer.extend(data)
            print(f"Read {len(buffer)} / {total_bytes} bytes", end="\r")

        print("\nCapture complete")
        ser.write(CMD_STOP)
        ser.flush()

    raw_path.write_bytes(buffer)
    print(f"Saved raw capture to {raw_path}")

    channel_bytes, data = extract_channels(bytes(buffer), channels=CHANNELS)
    ch1_raw_path.write_bytes(channel_bytes[0])
    ch2_raw_path.write_bytes(channel_bytes[1])
    print(f"Saved channel raw captures to {ch1_raw_path} and {ch2_raw_path}")

    if args.save_wav:
        write_wav(ch1_wav_path, channel_bytes[0], SAMPLE_RATE_HZ, channels=1)
        write_wav(ch2_wav_path, channel_bytes[1], SAMPLE_RATE_HZ, channels=1)
        print(f"Saved WAV files to {ch1_wav_path} and {ch2_wav_path}")

    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Saved metadata to {meta_path}")


if __name__ == "__main__":
    main()
