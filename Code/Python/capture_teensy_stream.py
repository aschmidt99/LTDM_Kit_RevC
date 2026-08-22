import argparse
import serial
import struct
import time
from pathlib import Path
from datetime import datetime
import json
from experiment_profile import ensure_experiment_profile
from path_layout import build_trial_paths
from trial_metadata_v2 import (
    infer_trial_status,
    iso_timestamps_pair,
    normalise_controls,
    normalise_flexpwm_timing,
    relative_path,
)

CMD_ARM = b'A'
CMD_STOP = b'T'
ARM_ACK = b'ARMED'
CAPTURE_MARKER = b'\xAA\x55'
TELEMETRY_PREFIX = b'@TLM1 '

DEFAULT_DURATION_S = 5
MAX_CAPTURE_SECONDS = 120
SAMPLE_RATE_HZ = 20000
CHANNELS = 2
ARM_ACK_TIMEOUT_S = 1.0
ARM_RETRY_COUNT = 5


def write_trial_manifest(manifest_path: Path, manifest: dict) -> None:
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


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


def _collect_telemetry_lines_in_place(buffer: bytearray, telemetry_frames: list[dict]) -> None:
    while True:
        newline_index = buffer.find(b"\n")
        if newline_index == -1:
            return
        raw_line = bytes(buffer[:newline_index]).rstrip(b"\r")
        del buffer[: newline_index + 1]
        stripped = raw_line.strip()
        if not stripped.startswith(TELEMETRY_PREFIX):
            continue
        payload_bytes = stripped[len(TELEMETRY_PREFIX) :]
        try:
            payload_text = payload_bytes.decode("utf-8")
            payload = json.loads(payload_text)
        except Exception:
            continue
        if isinstance(payload, dict):
            telemetry_frames.append(payload)


def read_until_capture_marker_with_telemetry(
    ser,
    marker: bytes,
    timeout: float | None,
    initial_buffer: bytes = b"",
):
    deadline = None if timeout is None else time.time() + timeout
    scan_buffer = bytearray(initial_buffer)
    telemetry_frames: list[dict] = []

    _collect_telemetry_lines_in_place(scan_buffer, telemetry_frames)

    while deadline is None or time.time() < deadline:
        marker_index = scan_buffer.find(marker)
        if marker_index != -1:
            prefix = bytearray(scan_buffer[:marker_index])
            _collect_telemetry_lines_in_place(prefix, telemetry_frames)
            leftover = bytes(scan_buffer[marker_index + len(marker) :])
            return True, leftover, telemetry_frames

        chunk = ser.read(ser.in_waiting or 1)
        if not chunk:
            continue
        scan_buffer.extend(chunk)
        _collect_telemetry_lines_in_place(scan_buffer, telemetry_frames)

        if len(scan_buffer) > 65536:
            scan_buffer = scan_buffer[-65536:]

    return False, b"", telemetry_frames


def get_arm_snapshot_telemetry(telemetry_frames: list[dict]) -> dict | None:
    for frame in telemetry_frames:
        if frame.get("message_type") == "arm_snapshot":
            return frame
    return None


def get_teensy_sample_rate_hz(arm_snapshot: dict | None, fallback_hz: int) -> int:
    if not isinstance(arm_snapshot, dict):
        return fallback_hz
    firmware = arm_snapshot.get("firmware")
    if not isinstance(firmware, dict):
        return fallback_hz
    value = firmware.get("samplerate_hz")
    try:
        sample_rate = int(value)
    except (TypeError, ValueError):
        return fallback_hz
    return sample_rate if sample_rate > 0 else fallback_hz


def prompt_duration(default_seconds: int) -> int:
    raw = input(f"Capture duration in seconds [{default_seconds}]: ").strip()
    if not raw:
        return default_seconds
    try:
        seconds = int(raw)
    except ValueError as exc:
        raise SystemExit("Capture duration must be an integer number of seconds") from exc
    if seconds <= 0 or seconds > MAX_CAPTURE_SECONDS:
        raise SystemExit(f"Capture duration must be between 1 and {MAX_CAPTURE_SECONDS} seconds")
    return seconds





def main():
    args = parse_args()
    duration_seconds = args.duration if args.duration is not None else prompt_duration(DEFAULT_DURATION_S)
    experiment_profile, experiment_profile_path, _ = ensure_experiment_profile(args.output_dir, args.experiment)
    layout = build_trial_paths(args.output_dir, args.experiment, args.trial, create=True)
    trial_dir = layout["trial_dir"]
    macro_audio_dir = layout["macro_audio_dir"]
    macro_audio_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "experiment_title": args.experiment,
        "trial_number": args.trial,
        "duration_seconds": duration_seconds,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "channels": CHANNELS,
        "capture_time": datetime.now().isoformat(),
        "experiment_profile": experiment_profile,
        "experiment_profile_path": str(experiment_profile_path),
    }

    raw_path = macro_audio_dir / "teensy_stream.bin"
    ch1_raw_path = macro_audio_dir / "teensy_stream_ch1.bin"
    ch2_raw_path = macro_audio_dir / "teensy_stream_ch2.bin"
    wav_path = macro_audio_dir / "teensy_stream.wav"
    ch1_wav_path = macro_audio_dir / "teensy_stream_ch1.wav"
    ch2_wav_path = macro_audio_dir / "teensy_stream_ch2.wav"
    meta_path = trial_dir / "trial_teensy_stream_metadata.json"
    schema_meta_path = trial_dir / "trial_metadata_v2.json"
    manifest_path = layout["trial_manifest_path"]

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
        ok, leftover, telemetry_frames = read_until_capture_marker_with_telemetry(
            ser,
            CAPTURE_MARKER,
            timeout=None,
            initial_buffer=leftover,
        )
        print("Capture start marker received")

        arm_snapshot = get_arm_snapshot_telemetry(telemetry_frames)
        teensy_sample_rate_hz = get_teensy_sample_rate_hz(arm_snapshot, SAMPLE_RATE_HZ)

        print(f"Capturing {duration_seconds} seconds of data...")
        total_samples = duration_seconds * teensy_sample_rate_hz
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
        write_wav(ch1_wav_path, channel_bytes[0], teensy_sample_rate_hz, channels=1)
        write_wav(ch2_wav_path, channel_bytes[1], teensy_sample_rate_hz, channels=1)
        print(f"Saved WAV files to {ch1_wav_path} and {ch2_wav_path}")

    metadata["sample_rate_hz"] = teensy_sample_rate_hz
    metadata["telemetry"] = {
        "frames_received": len(telemetry_frames),
        "arm_snapshot_present": isinstance(arm_snapshot, dict),
        "firmware_report_source": "firmware" if isinstance(arm_snapshot, dict) else "python_fallback",
        "protocol_version": str(arm_snapshot.get("protocol_version", "1")) if isinstance(arm_snapshot, dict) else "1",
    }

    meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Saved metadata to {meta_path}")

    stream_states = {
        "teensy": {
            "requested": True,
            "status": "success",
            "sample_rate_hz": teensy_sample_rate_hz,
            "channels": CHANNELS,
        },
        "interface": {
            "requested": False,
            "status": "skipped",
        },
        "rigol": {
            "requested": False,
            "status": "skipped",
        },
    }
    capture_time_utc, capture_time_local = iso_timestamps_pair()
    trial_metadata_v2 = {
        "schema_version": "2.0",
        "experiment_title": args.experiment,
        "trial_number": int(args.trial),
        "capture_profile": "teensy_only",
        "trial_status": infer_trial_status(stream_states),
        "capture_time_utc": capture_time_utc,
        "capture_time_local": capture_time_local,
        "firmware": {
            "samplerate_hz": teensy_sample_rate_hz,
            "protocol_version": str(arm_snapshot.get("protocol_version", "1")) if isinstance(arm_snapshot, dict) else "1",
            "report_source": "firmware" if isinstance(arm_snapshot, dict) else "python_fallback",
            "report_raw": arm_snapshot if isinstance(arm_snapshot, dict) else {},
        },
        "flexpwm_tdm_timing": normalise_flexpwm_timing(arm_snapshot, teensy_sample_rate_hz),
        "controls": normalise_controls(arm_snapshot),
        "streams": stream_states,
        "files": {
            "teensy": {
                "raw_bin": relative_path(raw_path, layout["exp_dir"]),
                "ch1_wav": relative_path(ch1_wav_path, layout["exp_dir"]),
                "ch2_wav": relative_path(ch2_wav_path, layout["exp_dir"]),
            },
            "manifests": {
                "trial_manifest": relative_path(manifest_path, layout["exp_dir"]),
                "trial_metadata": relative_path(schema_meta_path, layout["exp_dir"]),
            },
        },
        "experiment_profile_snapshot": experiment_profile,
    }
    schema_meta_path.write_text(json.dumps(trial_metadata_v2, indent=2), encoding="utf-8")
    metadata["schema_v2_path"] = str(schema_meta_path)
    print(f"Saved schema metadata to {schema_meta_path}")

    manifest = {
        "experiment_title": args.experiment,
        "trial_number": args.trial,
        "capture_time": metadata["capture_time"],
        "experiment_profile": experiment_profile,
        "experiment_profile_path": str(experiment_profile_path),
        "requested_streams": ["teensy"],
        "streams": {
            "teensy": {
                "requested": True,
                "enabled": True,
                "status": "completed",
                "sample_rate_hz": teensy_sample_rate_hz,
                "files": {
                    "raw": str(raw_path),
                    "ch1_bin": str(ch1_raw_path),
                    "ch2_bin": str(ch2_raw_path),
                    "ch1_wav": str(ch1_wav_path),
                    "ch2_wav": str(ch2_wav_path),
                    "metadata": str(meta_path),
                    "metadata_v2": str(schema_meta_path),
                },
            },
            "interface": {
                "requested": False,
                "enabled": False,
                "status": "skipped",
                "reason": "not captured by capture_teensy_stream.py",
            },
        },
        "completed_streams": ["teensy"],
        "skipped_streams": ["interface"],
    }
    write_trial_manifest(manifest_path, manifest)
    print(f"Saved trial manifest to {manifest_path}")


if __name__ == "__main__":
    main()
