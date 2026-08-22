import argparse
import json
import os
import select
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import serial
from experiment_profile import ensure_experiment_profile, ensure_scope_channel_labels
from path_layout import build_trial_paths
from trial_metadata_v2 import (
    infer_trial_status,
    iso_timestamps_pair,
    normalise_controls,
    normalise_flexpwm_timing,
    relative_path,
)

CMD_ARM = b"A"
CMD_STOP = b"T"
ARM_ACK = b"ARMED"
CAPTURE_MARKER = b"\xAA\x55"
TELEMETRY_PREFIX = b"@TLM1 "

DEFAULT_DURATION_S = 5
MAX_CAPTURE_SECONDS = 120
TEENSY_SAMPLE_RATE_HZ = 20000
TEENSY_CHANNELS = 2
ARM_ACK_TIMEOUT_S = 1.0
ARM_RETRY_COUNT = 5
IFACE_DEFAULT_SAMPLE_RATE_HZ = 192000
AUDACITY_STATE_FILENAME = "audacity_timeline_state.json"
AUDACITY_IFACE_CH1_TIMELINE = "_audacity_iface_ch1_timeline.wav"
AUDACITY_IFACE_CH2_TIMELINE = "_audacity_iface_ch2_timeline.wav"
AUDACITY_TEENSY_CH1_TIMELINE = "_audacity_teensy_ch1_timeline.wav"
AUDACITY_TEENSY_CH2_TIMELINE = "_audacity_teensy_ch2_timeline.wav"
AUDACITY_RESET_PASSES_DEFAULT = 8
AUDACITY_PRE_IMPORT_DELAY_S_DEFAULT = 0.75
AUDACITY_POST_IMPORT_DELAY_S_DEFAULT = 0.75
AUDACITY_PRE_SAVE_DELAY_S_DEFAULT = 0.6
AUDACITY_POST_SAVE_DELAY_S_DEFAULT = 0.4
DEBUG_LOGGING_ENABLED = False


def write_trial_manifest(manifest_path: Path, manifest: dict) -> None:
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def run_post_rigol_capture(experiment: str, trial: int) -> None:
    rigol_script = Path(__file__).with_name("rigol_capture.py")
    if not rigol_script.exists():
        raise SystemExit(f"Rigol capture script not found: {rigol_script}")

    cmd = [
        os.sys.executable,
        str(rigol_script),
        "--experiment",
        experiment,
        "--trial",
        str(trial),
    ]
    print("Starting Rigol capture for the same experiment/trial...")
    completed = subprocess.run(cmd)
    if completed.returncode != 0:
        raise SystemExit(int(completed.returncode))


def update_audacity_timeline(
    *,
    args,
    orchestration_dir: Path,
    audacity_dir: Path,
    iface_channel_paths,
    ch1_wav_path: Path,
    ch2_wav_path: Path,
):
    exp_dir = orchestration_dir.parent

    def ts_utc() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def rel(path: Path) -> str:
        try:
            return str(path.resolve().relative_to(exp_dir.resolve()))
        except Exception:
            return str(path)

    lifecycle_events = []

    def add_event(event: str, details: dict | None = None) -> None:
        lifecycle_events.append(
            {
                "ts_utc": ts_utc(),
                "event": event,
                "details": details or {},
            }
        )

    def q(path: Path) -> str:
        return str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')

    def send_checked(audacity: "AudacityPipe", command: str, timeout_s: float = 6.0) -> str:
        response = audacity.send(command, timeout_s=timeout_s)
        response_lower = response.lower()
        if "batchcommand finished: failed" in response_lower or "error:" in response_lower:
            raise RuntimeError(f"Audacity command failed: {command}; response: {response.strip()}")
        return response

    def send_checked_any(audacity: "AudacityPipe", commands: list[str], timeout_s: float = 6.0) -> tuple[str, str]:
        last_error = ""
        for cmd in commands:
            try:
                response = send_checked(audacity, cmd, timeout_s=timeout_s)
                return cmd, response
            except Exception as exc:
                last_error = str(exc)
        joined = " | ".join(commands)
        raise RuntimeError(f"All Audacity command variants failed: {joined}; last_error={last_error}")

    audacity_timeline = {
        "enabled": bool(args.audacity_import),
        "state_path": rel(orchestration_dir / AUDACITY_STATE_FILENAME),
        "project_path": rel(orchestration_dir / f"{safe_name(args.experiment)}.aup3"),
        "records": 0,
        "latest_start_s": 0.0,
        "latest_end_s": 0.0,
        "status": "skipped",
        "lifecycle_events": lifecycle_events,
    }
    if not args.audacity_import:
        add_event("close_project", {"status": "skipped", "reason": "audacity_import_disabled"})
        return audacity_timeline

    add_event("launch_attempt", {"state_path": audacity_timeline["state_path"]})

    if not iface_channel_paths or len(iface_channel_paths) < 2:
        add_event("error", {"message": "Audacity import requires interface_capture_ch1.wav and interface_capture_ch2.wav"})
        audacity_timeline["status"] = "failed"
        audacity_timeline["error"] = "Audacity import requires interface_capture_ch1.wav and interface_capture_ch2.wav"
        return audacity_timeline

    state_path = orchestration_dir / AUDACITY_STATE_FILENAME
    try:
        if args.audacity_reset_timeline or args.trial == 1:
            state = {"next_start_s": 0.0, "records": []}
        else:
            state = load_audacity_timeline_state(state_path)

        records = []
        for rec in state.get("records", []):
            if not isinstance(rec, dict):
                continue
            try:
                _ = int(rec.get("trial", -1))
                _ = float(rec.get("start_s", 0.0))
            except Exception:
                continue
            needed = ["iface_ch1", "iface_ch2", "teensy_ch1", "teensy_ch2"]
            if not all(Path(str(rec.get(k, ""))).exists() for k in needed):
                continue
            records.append(rec)

        prior_records_count = len(records)
        duration_s = wav_duration_seconds(ch1_wav_path)
        existing = next((r for r in records if int(r.get("trial", -1)) == int(args.trial)), None)
        if existing is not None:
            start_s = float(existing.get("start_s", 0.0))
            records = [r for r in records if int(r.get("trial", -1)) != int(args.trial)]
        else:
            start_s = float(state.get("next_start_s", 0.0))

        is_new_trial = existing is None
        trial_rec = {
            "trial": int(args.trial),
            "start_s": float(start_s),
            "duration_s": float(duration_s),
            "iface_ch1": str(iface_channel_paths[0].resolve()),
            "iface_ch2": str(iface_channel_paths[1].resolve()),
            "teensy_ch1": str(ch1_wav_path.resolve()),
            "teensy_ch2": str(ch2_wav_path.resolve()),
        }
        records.append(trial_rec)
        records = sorted(records, key=lambda r: float(r.get("start_s", 0.0)))

        next_start_s = 0.0
        for rec in records:
            rec_end = float(rec.get("start_s", 0.0)) + float(rec.get("duration_s", 0.0))
            next_start_s = max(next_start_s, rec_end)

        state = {
            "next_start_s": float(next_start_s),
            "records": records,
        }
        save_audacity_timeline_state(state_path, state)

        latest_end_s = float(trial_rec["start_s"]) + float(trial_rec["duration_s"])
        audacity = AudacityPipe(
            timeout_s=float(args.audacity_timeout),
            command_spacing_s=float(args.audacity_command_spacing),
        )
        project_path = orchestration_dir / f"{safe_name(args.experiment)}.aup3"
        legacy_project_path = orchestration_dir / "audacity_project.aup3"
        audacity.open()
        add_event("launch_success", {})
        try:
            should_attempt_open = bool(args.audacity_reset_timeline) or int(args.trial) == 1
            if should_attempt_open:
                if project_path.exists():
                    used_cmd, _ = send_checked_any(
                        audacity,
                        [
                            f'OpenProject2: Filename="{q(project_path)}"',
                            f'OpenProject: Filename="{q(project_path)}"',
                        ],
                        timeout_s=10.0,
                    )
                    add_event("open_project", {"path": rel(project_path), "command": used_cmd})
                elif legacy_project_path.exists():
                    used_cmd, _ = send_checked_any(
                        audacity,
                        [
                            f'OpenProject2: Filename="{q(legacy_project_path)}"',
                            f'OpenProject: Filename="{q(legacy_project_path)}"',
                        ],
                        timeout_s=10.0,
                    )
                    add_event("open_project", {"path": rel(legacy_project_path), "command": used_cmd, "legacy": True})
                else:
                    add_event("create_project", {"path": rel(project_path), "mode": "save_on_first_write"})
            else:
                add_event("open_project", {"status": "skipped", "reason": "follow_up_trial_assume_already_open"})

            do_full_rebuild = bool(args.audacity_reset_timeline) or prior_records_count == 0 or (not is_new_trial)
            if not do_full_rebuild:
                track_count = get_audacity_track_count(audacity)
                if track_count is not None and track_count < 4:
                    do_full_rebuild = True
                    add_event(
                        "create_project",
                        {
                            "mode": "auto_rebuild_due_to_missing_tracks",
                            "track_count": track_count,
                        },
                    )
            if do_full_rebuild:
                import_records_to_audacity(
                    audacity,
                    records,
                    playhead_s=latest_end_s,
                    reset_passes=max(1, int(args.audacity_reset_passes)),
                    pre_import_delay_s=max(0.0, float(args.audacity_pre_import_delay)),
                    post_import_delay_s=max(0.0, float(args.audacity_post_import_delay)),
                )
                add_event("import_tracks", {"mode": "rebuild", "records": len(records)})
            else:
                append_record_to_audacity(
                    audacity,
                    trial_rec,
                    playhead_s=latest_end_s,
                    pre_import_delay_s=max(0.0, float(args.audacity_pre_import_delay)),
                    post_import_delay_s=max(0.0, float(args.audacity_post_import_delay)),
                )
                add_event("import_tracks", {"mode": "append", "records": 1})

            pre_save_delay_s = max(0.0, float(args.audacity_pre_save_delay))
            if pre_save_delay_s > 0.0:
                time.sleep(pre_save_delay_s)

            used_cmd, _ = send_checked_any(
                audacity,
                [
                    f'SaveProject2: Filename="{q(project_path)}"',
                    f'SaveProject: Filename="{q(project_path)}"',
                ],
                timeout_s=10.0,
            )
            add_event("save_project", {"status": "saved", "path": rel(project_path), "command": used_cmd})
            audacity_timeline["status"] = "saved"

            post_save_delay_s = max(0.0, float(args.audacity_post_save_delay))
            if post_save_delay_s > 0.0:
                time.sleep(post_save_delay_s)
        finally:
            audacity.close()
            add_event("close_project", {"status": "closed_pipe"})

        dbg(
            f"audacity_timeline=records:{len(records)},latest_start_s:{trial_rec['start_s']:.3f},"
            f"latest_end_s:{latest_end_s:.3f},next_start_s:{next_start_s:.3f}"
        )

        audacity_timeline.update(
            {
                "enabled": True,
                "state_path": str(state_path),
                "records": len(records),
                "latest_start_s": float(trial_rec["start_s"]),
                "latest_end_s": float(latest_end_s),
                "next_start_s": float(next_start_s),
                "import_mode": "per-trial-clips-4-tracks",
                "rebuild_mode": bool(do_full_rebuild),
                "trial_audacity_dir": str(audacity_dir),
            }
        )
        return audacity_timeline
    except Exception as exc:
        add_event("error", {"message": str(exc)})
        audacity_timeline["status"] = "failed"
        audacity_timeline["error"] = str(exc)
        return audacity_timeline


def parse_args():
    parser = argparse.ArgumentParser(
        description="Phase 1: capture Teensy stream and audio-interface input in one Python run."
    )
    parser.add_argument("--port", required=True, help="Serial port for Teensy")
    parser.add_argument("--output-dir", default="experiments", help="Base output directory")
    parser.add_argument("--experiment", default="TeensyCapture", help="Experiment title")
    parser.add_argument("--trial", type=int, default=1, help="Trial number")
    parser.add_argument("--duration", type=int, default=None, help="Capture duration in seconds")
    parser.add_argument("--teensy-enable", action="store_true", default=True, help="Enable Teensy serial capture")
    parser.add_argument("--teensy-disable", dest="teensy_enable", action="store_false", help="Disable Teensy serial capture")

    parser.add_argument("--iface-enable", action="store_true", default=True, help="Enable interface capture")
    parser.add_argument("--iface-disable", dest="iface_enable", action="store_false", help="Disable interface capture")
    parser.add_argument("--iface-device", default=None, help="sounddevice input device (name or index)")
    parser.add_argument("--iface-channels", type=int, default=2, help="Interface input channel count")
    parser.add_argument("--iface-sample-rate", type=int, default=IFACE_DEFAULT_SAMPLE_RATE_HZ, help="Interface sample rate")
    parser.add_argument("--iface-subtype", default="PCM_16", help="WAV subtype for interface file")
    parser.add_argument(
        "--iface-start-mode",
        choices=["marker", "arm", "arm-gated"],
        default="arm-gated",
        help=(
            "When to start interface recording: "
            "'marker' starts stream on Teensy marker, "
            "'arm' starts before arming and saves whole stream, "
            "'arm-gated' starts before arming then trims to marker->stop window."
        ),
    )
    parser.add_argument("--iface-pre-roll", type=float, default=0.15, help="Seconds to record before arming Teensy")
    parser.add_argument("--iface-post-roll", type=float, default=0.15, help="Seconds to record after Teensy capture completes")
    parser.add_argument(
        "--iface-trim-to-teensy",
        action="store_true",
        default=True,
        help="Trim interface stream after alignment to exactly match Teensy duration.",
    )
    parser.add_argument(
        "--iface-no-trim-to-teensy",
        dest="iface_trim_to_teensy",
        action="store_false",
        help="Do not trim interface stream to Teensy duration.",
    )
    parser.add_argument(
        "--iface-auto-align",
        action="store_true",
        default=True,
        help="Auto-align interface capture to Teensy CH1 using per-trial envelope correlation.",
    )
    parser.add_argument(
        "--iface-no-auto-align",
        dest="iface_auto_align",
        action="store_false",
        help="Disable in-script interface alignment.",
    )
    parser.add_argument(
        "--iface-align-channel",
        type=int,
        default=1,
        help="1-based interface channel index used as alignment reference.",
    )
    parser.add_argument(
        "--iface-align-max-offset-s",
        type=float,
        default=2.0,
        help="Max absolute lag to search during alignment, in seconds.",
    )
    parser.add_argument(
        "--iface-align-envelope-ms",
        type=float,
        default=2.0,
        help="Envelope smoothing window in milliseconds for alignment.",
    )
    parser.add_argument(
        "--iface-align-analysis-hz",
        type=int,
        default=1000,
        help="Downsampled analysis rate for correlation (higher = finer but slower).",
    )
    parser.add_argument("--iface-list-devices", action="store_true", help="List interface devices and exit")
    parser.add_argument(
        "--audacity-import",
        action="store_true",
        default=True,
        help="Import/update timeline tracks in Audacity after each trial.",
    )
    parser.add_argument(
        "--no-audacity-import",
        dest="audacity_import",
        action="store_false",
        help="Disable Audacity import automation.",
    )
    parser.add_argument(
        "--audacity-command-spacing",
        type=float,
        default=0.35,
        help="Minimum seconds between Audacity script-pipe commands.",
    )
    parser.add_argument(
        "--audacity-timeout",
        type=float,
        default=3.0,
        help="Default timeout seconds for Audacity script-pipe responses.",
    )
    parser.add_argument(
        "--audacity-reset-passes",
        type=int,
        default=AUDACITY_RESET_PASSES_DEFAULT,
        help="How many remove attempts to clear existing project tracks before import.",
    )
    parser.add_argument(
        "--audacity-pre-import-delay",
        type=float,
        default=AUDACITY_PRE_IMPORT_DELAY_S_DEFAULT,
        help="Seconds to wait after reset before importing timeline tracks.",
    )
    parser.add_argument(
        "--audacity-post-import-delay",
        type=float,
        default=AUDACITY_POST_IMPORT_DELAY_S_DEFAULT,
        help="Seconds to wait after importing timeline tracks and moving playhead.",
    )
    parser.add_argument(
        "--audacity-pre-save-delay",
        type=float,
        default=AUDACITY_PRE_SAVE_DELAY_S_DEFAULT,
        help="Extra settle time before saving Audacity project.",
    )
    parser.add_argument(
        "--audacity-post-save-delay",
        type=float,
        default=AUDACITY_POST_SAVE_DELAY_S_DEFAULT,
        help="Extra settle time after saving Audacity project before closing script pipe.",
    )
    parser.add_argument(
        "--audacity-reset-timeline",
        action="store_true",
        help="Reset Audacity timeline state for this experiment before appending this trial.",
    )
    parser.add_argument(
        "--post-rigol",
        action="store_true",
        help="Run rigol_capture.py for the same experiment/trial after audio capture files are saved.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose [DBG] timing/alignment diagnostics in terminal output.",
    )

    return parser.parse_args()


def safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in value).strip().replace(" ", "_") or "untitled"


def write_wav(filename: Path, samples: bytes, sample_rate: int, channels: int):
    import wave

    with wave.open(str(filename), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples)


def wav_duration_seconds(path: Path) -> float:
    import wave

    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def write_silence_wav(path: Path, duration_s: float, sample_rate: int) -> None:
    import wave

    total_frames = max(0, int(round(max(0.0, float(duration_s)) * float(sample_rate))))
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * total_frames)


def extract_channels(buffer: bytes, channels: int = 2):
    from array import array

    samples = array("h")
    samples.frombytes(buffer)
    if len(samples) % channels != 0:
        raise ValueError(f"Binary capture length not divisible by {channels}: {len(samples)}")

    channel_bytes = []
    for ch in range(channels):
        channel_data = array("h", samples[ch::channels])
        channel_bytes.append(channel_data.tobytes())
    return channel_bytes


def read_until_marker(ser, marker: bytes, timeout: float | None):
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
        if len(buffer) > len(marker) * 8:
            buffer = buffer[-len(marker) * 8 :]
    return False, b""


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


def dbg(msg: str):
    if DEBUG_LOGGING_ENABLED:
        print(f"[DBG] {msg}")


class AudacityPipe:
    def __init__(self, timeout_s: float = 3.0, command_spacing_s: float = 0.35):
        uid = os.getuid()
        self.to_path = Path(f"/tmp/audacity_script_pipe.to.{uid}")
        self.from_path = Path(f"/tmp/audacity_script_pipe.from.{uid}")
        self.timeout_s = timeout_s
        self.command_spacing_s = max(0.0, float(command_spacing_s))
        self.to_pipe = None
        self.from_pipe = None
        self._last_send_time = 0.0

    def open(self):
        # Avoid blocking on stale FIFO paths when Audacity is not running.
        proc = subprocess.run(["pgrep", "-x", "Audacity"], capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError("Audacity is not running.")

        if not self.to_path.exists() or not self.from_path.exists():
            raise RuntimeError("Audacity mod-script-pipe not available. Open Audacity with mod-script-pipe enabled.")
        self.to_pipe = self.to_path.open("w", encoding="utf-8", buffering=1)
        self.from_pipe = self.from_path.open("r", encoding="utf-8", buffering=1)

    def close(self):
        if self.to_pipe:
            self.to_pipe.close()
            self.to_pipe = None
        if self.from_pipe:
            self.from_pipe.close()
            self.from_pipe = None

    def send(self, command: str, timeout_s: float | None = None) -> str:
        if self.to_pipe is None or self.from_pipe is None:
            raise RuntimeError("Audacity pipe is not open")

        now = time.time()
        elapsed = now - self._last_send_time
        if self.command_spacing_s > 0.0 and elapsed < self.command_spacing_s:
            time.sleep(self.command_spacing_s - elapsed)

        self.to_pipe.write(command + "\n")
        self.to_pipe.flush()
        self._last_send_time = time.time()

        fd = self.from_pipe.fileno()
        response_lines = []
        timeout = self.timeout_s if timeout_s is None else timeout_s
        deadline = time.time() + timeout

        while time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            readable, _, _ = select.select([fd], [], [], remaining)
            if not readable:
                continue
            line = self.from_pipe.readline()
            if line == "":
                break
            response_lines.append(line)
            if line.strip() == "":
                break

        return "".join(response_lines)


def load_audacity_timeline_state(state_path: Path):
    if not state_path.exists():
        return {"next_start_s": 0.0, "records": []}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {"next_start_s": 0.0, "records": []}
    if not isinstance(data, dict):
        return {"next_start_s": 0.0, "records": []}
    records = data.get("records", [])
    if not isinstance(records, list):
        records = []
    next_start_s = float(data.get("next_start_s", 0.0))
    return {"next_start_s": next_start_s, "records": records}


def save_audacity_timeline_state(state_path: Path, state):
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def get_audacity_track_count(audacity: AudacityPipe) -> int | None:
    resp = audacity.send("GetInfo: Type=Tracks Format=JSON", timeout_s=6.0)
    payload_lines = [ln for ln in resp.splitlines() if not ln.startswith("BatchCommand finished")]
    payload = "\n".join(payload_lines).strip()
    if not payload:
        return None
    try:
        parsed = json.loads(payload)
    except Exception:
        return None
    if isinstance(parsed, list):
        return len(parsed)
    if isinstance(parsed, dict):
        tracks = parsed.get("tracks")
        if isinstance(tracks, list):
            return len(tracks)
    return None


def read_mono_wav(path: Path):
    import wave

    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise RuntimeError(f"Expected mono 16-bit WAV: {path}")
        sr = wf.getframerate()
        pcm = wf.readframes(wf.getnframes())
    return sr, pcm


def build_mono_timeline_wav(records, key: str, out_path: Path):
    import wave

    if not records:
        # Write empty 16-bit mono file at a reasonable default.
        with wave.open(str(out_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(IFACE_DEFAULT_SAMPLE_RATE_HZ)
            wf.writeframes(b"")
        return

    first_sr, _ = read_mono_wav(Path(records[0][key]))
    timeline = bytearray()
    for rec in sorted(records, key=lambda r: float(r["start_s"])):
        wav_path = Path(rec[key])
        sr, pcm = read_mono_wav(wav_path)
        if sr != first_sr:
            raise RuntimeError(f"Sample-rate mismatch for {key}: expected {first_sr}, got {sr} at {wav_path}")
        start_samples = int(round(max(0.0, float(rec["start_s"])) * first_sr))
        start_bytes = start_samples * 2
        end_bytes = start_bytes + len(pcm)
        if len(timeline) < start_bytes:
            timeline.extend(b"\x00" * (start_bytes - len(timeline)))
        if len(timeline) < end_bytes:
            timeline.extend(b"\x00" * (end_bytes - len(timeline)))
        timeline[start_bytes:end_bytes] = pcm

    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(first_sr)
        wf.writeframes(bytes(timeline))


def reset_audacity_project_tracks(audacity: AudacityPipe, passes: int = AUDACITY_RESET_PASSES_DEFAULT):
    count = get_audacity_track_count(audacity)
    if count is not None:
        max_iters = max(8, count + max(0, int(passes)) + 8)
        for _ in range(max_iters):
            count = get_audacity_track_count(audacity)
            if count is None:
                break
            if count <= 0:
                return
            audacity.send("SelAllTracks")
            audacity.send("RemoveTracks")
            time.sleep(0.02)

    # Fallback for older/unsupported GetInfo behavior.
    for _ in range(max(0, passes)):
        audacity.send("SelAllTracks")
        audacity.send("RemoveTracks")
        time.sleep(0.02)


def import_records_to_audacity(
    audacity: AudacityPipe,
    records: list[dict],
    playhead_s: float,
    reset_passes: int,
    pre_import_delay_s: float,
    post_import_delay_s: float,
):
    def q(path: Path) -> str:
        return str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')

    def q_text(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    def clip_title_for(key: str, trial: int) -> str:
        base = {
            "iface_ch1": "interface_capture_ch1",
            "iface_ch2": "interface_capture_ch2",
            "teensy_ch1": "teensy_capture_ch1",
            "teensy_ch2": "teensy_capture_ch2",
        }.get(key, key)
        return f"{base}_trial{int(trial)}"

    def import_file(path: Path):
        audacity.send(f'Import2: Filename="{q(path)}"', timeout_s=6.0)

    def get_last_track_index() -> int:
        count = get_audacity_track_count(audacity)
        if count is not None and count > 0:
            return count - 1
        return 4

    def copy_track(track_idx: int):
        audacity.send(f"SelectTracks: Track={track_idx} TrackCount=1 Mode=Set")
        audacity.send("SelTrackStartToEnd")
        audacity.send("Copy")

    def paste_to_track(track_idx: int, at_s: float):
        audacity.send(f"SelectTracks: Track={track_idx} TrackCount=1 Mode=Set")
        audacity.send(f"SelectTime: Start={at_s:.6f} End={at_s:.6f} RelativeTo=ProjectStart")
        audacity.send("Paste")

    def remove_track(track_idx: int):
        audacity.send(f"SelectTracks: Track={track_idx} TrackCount=1 Mode=Set")
        audacity.send("RemoveTracks")

    def set_clip_title(track_idx: int, at_s: float, title: str):
        # Use a point just inside the clip to avoid boundary ambiguity at joins.
        clip_probe_s = max(0.0, float(at_s) + 0.001)
        audacity.send(f"SelectTracks: Track={track_idx} TrackCount=1 Mode=Set")
        audacity.send(f'SetClip: At={clip_probe_s:.6f} Name="{q_text(title)}"')

    if not records:
        return

    track_keys = ["iface_ch1", "iface_ch2", "teensy_ch1", "teensy_ch2"]

    reset_audacity_project_tracks(audacity, passes=reset_passes)
    if pre_import_delay_s > 0.0:
        time.sleep(pre_import_delay_s)

    # Seed base 4 tracks with first trial clips in fixed order.
    first = records[0]
    for key in track_keys:
        import_file(Path(first[key]))
    for target_idx, key in enumerate(track_keys):
        set_clip_title(target_idx, float(first.get("start_s", 0.0)), clip_title_for(key, int(first.get("trial", 0))))

    # For each subsequent trial, import each clip temporarily and paste into its target track.
    for rec in records[1:]:
        at_s = float(rec.get("start_s", 0.0))
        for target_idx, key in enumerate(track_keys):
            import_file(Path(rec[key]))
            temp_idx = get_last_track_index()
            copy_track(temp_idx)
            paste_to_track(target_idx, at_s)
            set_clip_title(target_idx, at_s, clip_title_for(key, int(rec.get("trial", 0))))
            remove_track(temp_idx)

    audacity.send(f"SelectTime: Start={playhead_s:.6f} End={playhead_s:.6f} RelativeTo=ProjectStart")
    if post_import_delay_s > 0.0:
        time.sleep(post_import_delay_s)


def append_record_to_audacity(
    audacity: AudacityPipe,
    rec: dict,
    playhead_s: float,
    pre_import_delay_s: float,
    post_import_delay_s: float,
):
    def q(path: Path) -> str:
        return str(path.resolve()).replace("\\", "\\\\").replace('"', '\\"')

    def q_text(value: str) -> str:
        return str(value).replace("\\", "\\\\").replace('"', '\\"')

    def clip_title_for(key: str, trial: int) -> str:
        base = {
            "iface_ch1": "interface_capture_ch1",
            "iface_ch2": "interface_capture_ch2",
            "teensy_ch1": "teensy_capture_ch1",
            "teensy_ch2": "teensy_capture_ch2",
        }.get(key, key)
        return f"{base}_trial{int(trial)}"

    def import_file(path: Path):
        audacity.send(f'Import2: Filename="{q(path)}"', timeout_s=6.0)

    def get_last_track_index() -> int:
        count = get_audacity_track_count(audacity)
        if count is not None and count > 0:
            return count - 1
        return 4

    def copy_track(track_idx: int):
        audacity.send(f"SelectTracks: Track={track_idx} TrackCount=1 Mode=Set")
        audacity.send("SelTrackStartToEnd")
        audacity.send("Copy")

    def paste_to_track(track_idx: int, at_s: float):
        audacity.send(f"SelectTracks: Track={track_idx} TrackCount=1 Mode=Set")
        audacity.send(f"SelectTime: Start={at_s:.6f} End={at_s:.6f} RelativeTo=ProjectStart")
        audacity.send("Paste")

    def remove_track(track_idx: int):
        audacity.send(f"SelectTracks: Track={track_idx} TrackCount=1 Mode=Set")
        audacity.send("RemoveTracks")

    def set_clip_title(track_idx: int, at_s: float, title: str):
        # Use a point just inside the clip to avoid boundary ambiguity at joins.
        clip_probe_s = max(0.0, float(at_s) + 0.001)
        audacity.send(f"SelectTracks: Track={track_idx} TrackCount=1 Mode=Set")
        audacity.send(f'SetClip: At={clip_probe_s:.6f} Name="{q_text(title)}"')

    if pre_import_delay_s > 0.0:
        time.sleep(pre_import_delay_s)

    track_keys = ["iface_ch1", "iface_ch2", "teensy_ch1", "teensy_ch2"]
    # Slight epsilon avoids edge-case paste errors when inserting at exact track end.
    at_s = max(0.0, float(rec.get("start_s", 0.0)) - 1e-6)
    for target_idx, key in enumerate(track_keys):
        import_file(Path(rec[key]))
        temp_idx = get_last_track_index()
        copy_track(temp_idx)
        paste_to_track(target_idx, at_s)
        set_clip_title(target_idx, at_s, clip_title_for(key, int(rec.get("trial", 0))))
        remove_track(temp_idx)

    audacity.send(f"SelectTime: Start={playhead_s:.6f} End={playhead_s:.6f} RelativeTo=ProjectStart")
    if post_import_delay_s > 0.0:
        time.sleep(post_import_delay_s)


def moving_average(x, window: int):
    import numpy as np

    if window <= 1:
        return x
    kernel = np.ones(window, dtype=np.float64) / float(window)
    return np.convolve(x, kernel, mode="same")


def estimate_interface_lag_samples(
    teensy_ch1_i16,
    teensy_sr: int,
    iface_ref_i16,
    iface_sr: int,
    max_offset_s: float,
    envelope_ms: float,
    analysis_hz: int,
):
    import numpy as np

    teensy = np.asarray(teensy_ch1_i16, dtype=np.float64)
    iface = np.asarray(iface_ref_i16, dtype=np.float64)
    if teensy.size < 100 or iface.size < 100:
        return 0, 0.0

    # Resample interface reference channel to Teensy sample rate.
    t_iface = np.arange(iface.size, dtype=np.float64) / float(iface_sr)
    n_iface_rs = max(1, int(round(iface.size * float(teensy_sr) / float(iface_sr))))
    t_iface_rs = np.arange(n_iface_rs, dtype=np.float64) / float(teensy_sr)
    iface_rs = np.interp(t_iface_rs, t_iface, iface)

    n = min(teensy.size, iface_rs.size)
    teensy = teensy[:n]
    iface_rs = iface_rs[:n]

    smooth_n = max(1, int(round(float(teensy_sr) * (envelope_ms / 1000.0))))
    env_t = moving_average(np.abs(teensy), smooth_n)
    env_i = moving_average(np.abs(iface_rs), smooth_n)

    env_t = env_t - np.mean(env_t)
    env_i = env_i - np.mean(env_i)
    std_t = np.std(env_t)
    std_i = np.std(env_i)
    if std_t > 0:
        env_t /= std_t
    if std_i > 0:
        env_i /= std_i

    # Downsample for affordable correlation with ~1 ms resolution.
    analysis_hz = max(100, int(analysis_hz))
    decim = max(1, int(round(float(teensy_sr) / float(analysis_hz))))
    env_t_d = env_t[::decim]
    env_i_d = env_i[::decim]
    analysis_sr = float(teensy_sr) / float(decim)

    corr = np.correlate(env_i_d, env_t_d, mode="full")
    lags = np.arange(-env_t_d.size + 1, env_i_d.size)

    max_lag_d = int(round(max(0.0, max_offset_s) * analysis_sr))
    mask = (lags >= -max_lag_d) & (lags <= max_lag_d)
    if not np.any(mask):
        return 0, 0.0

    corr_m = corr[mask]
    lags_m = lags[mask]
    idx = int(np.argmax(corr_m))
    lag_d = int(lags_m[idx])
    lag_samples = int(round(lag_d * decim))

    peak = float(corr_m[idx])
    base = float(np.std(corr_m) + 1e-12)
    score = peak / base
    return lag_samples, score


def shift_interface_data(data, shift_samples: int):
    import numpy as np

    out = np.zeros_like(data)
    n = data.shape[0]
    if shift_samples > 0:
        # Interface is late; advance it by dropping initial samples.
        kept = max(0, n - shift_samples)
        if kept > 0:
            out[:kept, :] = data[shift_samples:shift_samples + kept, :]
    elif shift_samples < 0:
        # Interface is early; delay it by padding the front.
        delay = -shift_samples
        kept = max(0, n - delay)
        if kept > 0:
            out[delay:delay + kept, :] = data[:kept, :]
    else:
        out[:, :] = data
    return out


def normalize_device_arg(device_arg):
    if device_arg is None:
        return None
    if isinstance(device_arg, str):
        text = device_arg.strip()
        if text.isdigit():
            return int(text)
    return device_arg


class InterfaceRecorder:
    def __init__(self, device, channels: int, sample_rate: int):
        self.device = device
        self.channels = channels
        self.sample_rate = sample_rate
        self._sd = None
        self._np = None
        self._stream = None
        self._blocks = []
        self.started_at = None
        self.stopped_at = None

    def setup(self):
        try:
            import numpy as np
            import sounddevice as sd
        except Exception as exc:
            raise RuntimeError(
                "Interface capture requires numpy and sounddevice. "
                "Install with: python3 -m pip install numpy sounddevice soundfile"
            ) from exc
        self._sd = sd
        self._np = np

    @staticmethod
    def list_devices():
        try:
            import sounddevice as sd
        except Exception as exc:
            raise RuntimeError(
                "Listing devices requires sounddevice. Install with: python3 -m pip install sounddevice"
            ) from exc
        print(sd.query_devices())

    def start(self):
        if self._sd is None or self._np is None:
            self.setup()

        self._blocks = []
        resolved_device = normalize_device_arg(self.device)
        try:
            info = self._sd.query_devices(resolved_device, kind="input")
            max_inputs = int(info.get("max_input_channels", 0))
            if max_inputs < self.channels:
                raise RuntimeError(
                    f"Device {resolved_device} has only {max_inputs} input channels; "
                    f"requested {self.channels}."
                )
            dbg(
                f"iface_device_resolved=name:{info.get('name')},index:{resolved_device},"
                f"max_input_channels:{max_inputs},default_samplerate:{info.get('default_samplerate')}"
            )
        except Exception as exc:
            raise RuntimeError(f"Failed to validate interface input device {resolved_device}: {exc}") from exc

        def callback(indata, frames, time_info, status):
            if status:
                print(f"[IFACE] status: {status}")
            self._blocks.append(indata.copy())

        self._stream = self._sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype="int16",
            device=resolved_device,
            callback=callback,
            blocksize=0,
        )
        self._stream.start()
        self.started_at = time.time()

    def stop(self):
        if self._stream is None:
            return self._np.zeros((0, self.channels), dtype=self._np.int16), {
                "duration_s": 0.0,
                "frames": 0,
                "rms": [],
                "peak": [],
            }

        self._stream.stop()
        self._stream.close()
        self.stopped_at = time.time()

        if self._blocks:
            data = self._np.concatenate(self._blocks, axis=0)
        else:
            data = self._np.zeros((0, self.channels), dtype=self._np.int16)

        stats = {
            "duration_s": float(data.shape[0]) / float(self.sample_rate),
            "frames": int(data.shape[0]),
            "rms": [],
            "peak": [],
        }
        if data.shape[0] > 0 and data.shape[1] > 0:
            float_data = data.astype(self._np.float64)
            for ch in range(data.shape[1]):
                col = float_data[:, ch]
                rms = float(self._np.sqrt(self._np.mean(col * col)))
                peak = float(self._np.max(self._np.abs(col)))
                stats["rms"].append(rms)
                stats["peak"].append(peak)
        return data, stats


def compute_interface_stats(data, sample_rate: int):
    import numpy as np

    stats = {
        "duration_s": float(data.shape[0]) / float(sample_rate),
        "frames": int(data.shape[0]),
        "rms": [],
        "peak": [],
    }
    if data.shape[0] > 0 and data.shape[1] > 0:
        float_data = data.astype(np.float64)
        for ch in range(data.shape[1]):
            col = float_data[:, ch]
            rms = float(np.sqrt(np.mean(col * col)))
            peak = float(np.max(np.abs(col)))
            stats["rms"].append(rms)
            stats["peak"].append(peak)
    return stats


def save_interface_wav_channels(data, sample_rate: int, out_dir: Path, channels: int, subtype: str = "PCM_16"):
    import soundfile as sf

    out_paths = []
    channel_count = min(channels, data.shape[1])
    for ch in range(channel_count):
        out_path = out_dir / f"interface_capture_ch{ch + 1}.wav"
        sf.write(str(out_path), data[:, ch], sample_rate, subtype=subtype)
        out_paths.append(out_path)
    return out_paths


def main():
    global DEBUG_LOGGING_ENABLED
    args = parse_args()
    DEBUG_LOGGING_ENABLED = bool(args.debug)

    if args.iface_list_devices:
        InterfaceRecorder.list_devices()
        return

    duration_seconds = args.duration if args.duration is not None else prompt_duration(DEFAULT_DURATION_S)
    experiment_profile, experiment_profile_path, _ = ensure_experiment_profile(args.output_dir, args.experiment)
    if args.post_rigol:
        experiment_profile, experiment_profile_path, _ = ensure_scope_channel_labels(
            args.output_dir,
            args.experiment,
            experiment_profile,
            prompt_when_missing=True,
        )

    layout = build_trial_paths(args.output_dir, args.experiment, args.trial, create=True)
    exp_dir = layout["exp_dir"]
    trial_dir = layout["trial_dir"]
    macro_audio_dir = layout["macro_audio_dir"]
    orchestration_dir = layout["orchestration_dir"]
    audacity_dir = layout["audacity_dir"]
    manifest_path = layout["trial_manifest_path"]

    macro_audio_dir.mkdir(parents=True, exist_ok=True)

    raw_path = macro_audio_dir / "teensy_stream.bin"
    ch1_wav_path = macro_audio_dir / "teensy_stream_Ch1.wav"
    ch2_wav_path = macro_audio_dir / "teensy_stream_ch2.wav"
    meta_path = trial_dir / "trial_audio_capture_metadata.json"
    schema_meta_path = trial_dir / "trial_metadata_v2.json"

    iface = None
    if args.iface_enable:
        iface = InterfaceRecorder(
            device=args.iface_device,
            channels=args.iface_channels,
            sample_rate=args.iface_sample_rate,
        )
        iface.setup()

    if not args.teensy_enable and not args.iface_enable:
        raise SystemExit("At least one stream must be enabled: teensy or interface")

    t_record_cmd = None
    t_marker = None
    t_capture_done = None
    t_stop_cmd = None
    t_arm_send = None
    t_armed_ack = None
    t_wait_marker = None
    buffer = bytearray()
    ch_bytes = [b"", b""]
    telemetry_frames: list[dict] = []
    arm_snapshot: dict | None = None
    teensy_sample_rate_hz = TEENSY_SAMPLE_RATE_HZ

    try:
        if args.teensy_enable:
            if iface is not None and args.iface_start_mode in {"arm", "arm-gated"}:
                iface.start()
                dbg(
                    f"iface_start=device:{args.iface_device},sr:{args.iface_sample_rate},"
                    f"ch:{args.iface_channels},mode:{args.iface_start_mode},t0:{iface.started_at:.6f}"
                )
                if args.iface_pre_roll > 0:
                    time.sleep(args.iface_pre_roll)

            with serial.Serial(args.port, 2000000, timeout=1, dsrdtr=False, rtscts=False, xonxoff=False) as ser:
                time.sleep(0.5)
                ser.reset_input_buffer()
                ser.reset_output_buffer()

                arm_command = CMD_ARM + bytes([duration_seconds])
                armed = False
                leftover = b""
                for attempt in range(ARM_RETRY_COUNT):
                    print(f"Arming capture on {args.port} for {duration_seconds}s (attempt {attempt + 1})")
                    t_arm_send = time.time()
                    ser.write(arm_command)
                    ser.flush()
                    armed, leftover = read_until_marker(ser, ARM_ACK, timeout=ARM_ACK_TIMEOUT_S)
                    if armed:
                        t_armed_ack = time.time()
                        break
                    time.sleep(0.05)

                if not armed:
                    raise SystemExit("Timeout waiting for ARMED acknowledgement from Teensy")

                print("Teensy armed. Press LTDM Kit button 8 to start.")
                t_wait_marker = time.time()
                started, leftover, telemetry_frames = read_until_capture_marker_with_telemetry(
                    ser,
                    CAPTURE_MARKER,
                    timeout=None,
                    initial_buffer=leftover,
                )
                t_marker = time.time()
                if not started:
                    raise SystemExit("Failed waiting for capture start marker")

                arm_snapshot = get_arm_snapshot_telemetry(telemetry_frames)
                teensy_sample_rate_hz = get_teensy_sample_rate_hz(arm_snapshot, TEENSY_SAMPLE_RATE_HZ)

                if iface is not None and args.iface_start_mode == "marker":
                    iface.start()
                    dbg(
                        f"iface_start=device:{args.iface_device},sr:{args.iface_sample_rate},"
                        f"ch:{args.iface_channels},mode:marker,t0:{iface.started_at:.6f},"
                        f"after_marker_ms={(iface.started_at - t_marker) * 1000.0:.1f}"
                    )

                t_record_cmd = time.time()

                total_samples = duration_seconds * teensy_sample_rate_hz
                total_bytes = total_samples * TEENSY_CHANNELS * 2
                buffer = bytearray(leftover)

                while len(buffer) < total_bytes:
                    data = ser.read(total_bytes - len(buffer))
                    if not data:
                        continue
                    buffer.extend(data)
                    print(f"Read {len(buffer)} / {total_bytes} bytes", end="\r")

                print("\nTeensy capture complete")
                t_capture_done = time.time()
                ser.write(CMD_STOP)
                ser.flush()
                t_stop_cmd = time.time()

            if iface is not None and args.iface_post_roll > 0:
                time.sleep(args.iface_post_roll)

            # Prepare Teensy channel buffers before optional interface alignment.
            ch_bytes = extract_channels(bytes(buffer), channels=TEENSY_CHANNELS)
        else:
            if iface is None:
                raise SystemExit("Interface-only mode requires --iface-enable")
            print(f"Interface-only mode: recording {duration_seconds}s from interface input")
            iface.start()
            t_wait_marker = time.time()
            t_marker = t_wait_marker
            t_record_cmd = t_wait_marker
            time.sleep(duration_seconds)
            t_capture_done = time.time()
            t_stop_cmd = t_capture_done

        iface_stats = {
            "duration_s": 0.0,
            "frames": 0,
            "rms": [],
            "peak": [],
        }
        iface_channel_paths = []
        lag_teensy_samples = 0
        lag_iface_samples = 0
        align_score = 0.0
        if iface is not None:
            iface_data, iface_stats = iface.stop()

            if args.teensy_enable and args.iface_start_mode == "arm-gated" and iface.started_at is not None:
                start_idx = int(round(max(0.0, (t_marker - iface.started_at) * args.iface_sample_rate)))
                end_time = t_stop_cmd + max(0.0, args.iface_post_roll)
                end_idx = int(round(max(0.0, (end_time - iface.started_at) * args.iface_sample_rate)))
                end_idx = min(end_idx, iface_data.shape[0])
                start_idx = min(start_idx, end_idx)
                iface_data = iface_data[start_idx:end_idx, :]
                iface_stats = compute_interface_stats(iface_data, args.iface_sample_rate)
                dbg(
                    f"iface_gate=mode:arm-gated,start_idx:{start_idx},end_idx:{end_idx},"
                    f"gated_dur_s:{iface_stats['duration_s']:.3f}"
                )

            if args.teensy_enable and args.iface_auto_align and iface_data.shape[0] > 0:
                align_ch_idx = max(0, min(args.iface_channels - 1, args.iface_align_channel - 1))
                teensy_ch1_i16 = ch_bytes[0]
                if teensy_ch1_i16:
                    import numpy as np

                    lag_teensy_samples, align_score = estimate_interface_lag_samples(
                        teensy_ch1_i16=np.frombuffer(teensy_ch1_i16, dtype=np.int16),
                        teensy_sr=teensy_sample_rate_hz,
                        iface_ref_i16=iface_data[:, align_ch_idx],
                        iface_sr=args.iface_sample_rate,
                        max_offset_s=args.iface_align_max_offset_s,
                        envelope_ms=args.iface_align_envelope_ms,
                        analysis_hz=args.iface_align_analysis_hz,
                    )
                    lag_iface_samples = int(
                        round(lag_teensy_samples * float(args.iface_sample_rate) / float(teensy_sample_rate_hz))
                    )
                    iface_data = shift_interface_data(iface_data, lag_iface_samples)
                    iface_stats = compute_interface_stats(iface_data, args.iface_sample_rate)
                    dbg(
                        f"iface_align=enabled,ref_ch:{align_ch_idx + 1},"
                        f"lag_teensy_samples:{lag_teensy_samples},"
                        f"lag_iface_samples:{lag_iface_samples},"
                        f"lag_ms:{(1000.0 * lag_iface_samples / args.iface_sample_rate):.2f},"
                        f"score:{align_score:.2f}"
                    )

            if args.teensy_enable and args.iface_trim_to_teensy and iface_data.shape[0] > 0:
                teensy_samples = len(ch_bytes[0]) // 2
                target_iface_samples = int(
                    round(teensy_samples * float(args.iface_sample_rate) / float(teensy_sample_rate_hz))
                )
                target_iface_samples = max(0, target_iface_samples)
                current_samples = iface_data.shape[0]
                if current_samples >= target_iface_samples:
                    iface_data = iface_data[:target_iface_samples, :]
                else:
                    import numpy as np

                    pad = np.zeros((target_iface_samples - current_samples, iface_data.shape[1]), dtype=iface_data.dtype)
                    iface_data = np.concatenate([iface_data, pad], axis=0)
                iface_stats = compute_interface_stats(iface_data, args.iface_sample_rate)
                dbg(
                    f"iface_trim_to_teensy=enabled,target_samples:{target_iface_samples},"
                    f"current_samples:{current_samples},final_samples:{iface_data.shape[0]},"
                    f"final_dur_s:{iface_stats['duration_s']:.3f}"
                )

            iface_channel_paths = save_interface_wav_channels(
                iface_data,
                sample_rate=args.iface_sample_rate,
                out_dir=macro_audio_dir,
                channels=args.iface_channels,
                subtype=args.iface_subtype,
            )
            dbg(
                f"iface_stop=t1:{iface.stopped_at:.6f},dur_s:{iface_stats['duration_s']:.3f},"
                f"frames:{iface_stats['frames']},files:{[p.name for p in iface_channel_paths]}"
            )
            if iface_stats["rms"]:
                for ch_idx, (rms, peak) in enumerate(zip(iface_stats["rms"], iface_stats["peak"]), start=1):
                    dbg(f"iface_ch{ch_idx}_rms={rms:.2f},peak={peak:.2f}")

        if args.teensy_enable:
            raw_path.write_bytes(buffer)
            write_wav(ch1_wav_path, ch_bytes[0], teensy_sample_rate_hz, channels=1)
            write_wav(ch2_wav_path, ch_bytes[1], teensy_sample_rate_hz, channels=1)

            if t_arm_send is not None and t_armed_ack is not None:
                dbg(f"arm_ack_ms={(t_armed_ack - t_arm_send) * 1000.0:.1f}")
            dbg(f"wait_for_marker_s={(t_marker - t_wait_marker):.3f}")
            dbg(f"record_cmd_after_marker_ms={(t_record_cmd - t_marker) * 1000.0:.1f}")
            dbg(f"teensy_capture_after_marker_s={(t_capture_done - t_marker):.3f}")
            dbg(f"teensy_stop_after_marker_s={(t_stop_cmd - t_marker):.3f}")
            dbg(
                "teensy_wav_durations_s="
                f"ch1:{wav_duration_seconds(ch1_wav_path):.3f},"
                f"ch2:{wav_duration_seconds(ch2_wav_path):.3f}"
            )

        audacity_timeline = {
            "enabled": bool(args.audacity_import),
            "state_path": str(orchestration_dir / AUDACITY_STATE_FILENAME),
            "records": 0,
            "latest_start_s": 0.0,
            "latest_end_s": 0.0,
        }

        metadata = {
            "experiment_title": args.experiment,
            "trial_number": args.trial,
            "duration_seconds": duration_seconds,
            "capture_time": datetime.now().isoformat(),
            "teensy": {
                "enabled": bool(args.teensy_enable),
                "port": args.port,
                "sample_rate_hz": teensy_sample_rate_hz,
                "channels": TEENSY_CHANNELS,
            },
            "telemetry": {
                "frames_received": len(telemetry_frames),
                "arm_snapshot_present": isinstance(arm_snapshot, dict),
                "firmware_report_source": "firmware" if isinstance(arm_snapshot, dict) else "python_fallback",
                "protocol_version": str(arm_snapshot.get("protocol_version", "1")) if isinstance(arm_snapshot, dict) else "1",
            },
            "debug_logging_enabled": bool(DEBUG_LOGGING_ENABLED),
            "interface": {
                "enabled": bool(args.iface_enable),
                "device": args.iface_device,
                "sample_rate_hz": args.iface_sample_rate,
                "channels": args.iface_channels,
                "start_mode": args.iface_start_mode,
                "auto_align": bool(args.iface_auto_align),
                "align_ref_channel": int(args.iface_align_channel),
                "align_max_offset_s": float(args.iface_align_max_offset_s),
                "align_envelope_ms": float(args.iface_align_envelope_ms),
                "align_analysis_hz": int(args.iface_align_analysis_hz),
                "pre_roll_s": args.iface_pre_roll,
                "post_roll_s": args.iface_post_roll,
                "trim_to_teensy": bool(args.iface_trim_to_teensy),
                "wav_duration_s": iface_stats["duration_s"],
                "wav_frames": iface_stats["frames"],
                "channel_rms": iface_stats["rms"],
                "channel_peak": iface_stats["peak"],
                "channel_wavs": [str(p) for p in iface_channel_paths],
                "alignment": {
                    "lag_teensy_samples": int(lag_teensy_samples),
                    "lag_iface_samples": int(lag_iface_samples),
                    "lag_ms": float(1000.0 * lag_iface_samples / args.iface_sample_rate)
                    if args.iface_sample_rate > 0
                    else 0.0,
                    "score": float(align_score),
                },
            },
            "timing": {
                "t_marker": t_marker,
                "t_record_cmd": t_record_cmd,
                "t_capture_done": t_capture_done,
                "t_teensy_stop": t_stop_cmd,
                "record_cmd_after_marker_ms": (t_record_cmd - t_marker) * 1000.0 if t_marker is not None and t_record_cmd is not None else None,
                "teensy_capture_after_marker_s": (t_capture_done - t_marker) if t_marker is not None and t_capture_done is not None else None,
            },
            "files": {
                "raw": str(raw_path) if args.teensy_enable else "",
                "teensy_ch1_wav": str(ch1_wav_path) if args.teensy_enable else "",
                "teensy_ch2_wav": str(ch2_wav_path) if args.teensy_enable else "",
                "interface_ch1_wav": str(iface_channel_paths[0]) if len(iface_channel_paths) > 0 else "",
                "interface_ch2_wav": str(iface_channel_paths[1]) if len(iface_channel_paths) > 1 else "",
            },
            "experiment_profile": experiment_profile,
            "experiment_profile_path": str(experiment_profile_path),
            "layout": {
                "experiment_dir": str(exp_dir),
                "trial_dir": str(trial_dir),
                "macro_audio_dir": str(layout["macro_audio_dir"]),
                "micro_scope_dir": str(layout["micro_scope_dir"]),
                "sync_dir": str(layout["sync_dir"]),
            },
            "audacity_timeline": audacity_timeline,
        }

        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        stream_states = {
            "teensy": {
                "requested": bool(args.teensy_enable),
                "enabled": bool(args.teensy_enable),
                "status": "completed" if args.teensy_enable else "skipped",
                "sample_rate_hz": teensy_sample_rate_hz if args.teensy_enable else None,
                "files": {
                    "raw": str(raw_path) if args.teensy_enable else "",
                    "ch1_wav": str(ch1_wav_path) if args.teensy_enable else "",
                    "ch2_wav": str(ch2_wav_path) if args.teensy_enable else "",
                    "metadata": str(meta_path),
                },
            },
            "interface": {
                "requested": bool(args.iface_enable),
                "enabled": bool(args.iface_enable),
                "status": "completed" if args.iface_enable else "skipped",
                "sample_rate_hz": int(args.iface_sample_rate) if args.iface_enable else None,
                "files": {
                    "ch1_wav": str(iface_channel_paths[0]) if len(iface_channel_paths) > 0 else "",
                    "ch2_wav": str(iface_channel_paths[1]) if len(iface_channel_paths) > 1 else "",
                },
            },
        }
        manifest = {
            "experiment_title": args.experiment,
            "trial_number": args.trial,
            "capture_time": metadata["capture_time"],
            "experiment_profile": experiment_profile,
            "experiment_profile_path": str(experiment_profile_path),
            "requested_streams": [name for name, state in stream_states.items() if state["requested"]],
            "completed_streams": [name for name, state in stream_states.items() if state["status"] == "completed"],
            "skipped_streams": [name for name, state in stream_states.items() if state["status"] == "skipped"],
            "streams": stream_states,
            "audacity": audacity_timeline,
        }
        schema_streams = {
            "teensy": {
                "requested": bool(args.teensy_enable),
                "status": "success" if args.teensy_enable else "skipped",
                "sample_rate_hz": teensy_sample_rate_hz if args.teensy_enable else None,
                "channels": TEENSY_CHANNELS if args.teensy_enable else None,
            },
            "interface": {
                "requested": bool(args.iface_enable),
                "status": "success" if args.iface_enable else "skipped",
                "sample_rate_hz": int(args.iface_sample_rate) if args.iface_enable else None,
                "channels": int(args.iface_channels) if args.iface_enable else None,
            },
            "rigol": {
                "requested": bool(args.post_rigol),
                "status": "success" if args.post_rigol else "skipped",
            },
        }
        capture_time_utc, capture_time_local = iso_timestamps_pair()
        trial_metadata_v2 = {
            "schema_version": "2.0",
            "experiment_title": args.experiment,
            "trial_number": int(args.trial),
            "capture_profile": "teensy_interface" if args.teensy_enable and args.iface_enable else (
                "teensy_only" if args.teensy_enable else "interface_only"
            ),
            "trial_status": infer_trial_status(schema_streams),
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
            "timing": {
                "monotonic": {
                    "t_arm_send_s": t_arm_send,
                    "t_armed_ack_s": t_armed_ack,
                    "t_marker_s": t_marker,
                    "t_capture_done_s": t_capture_done,
                    "t_stop_cmd_s": t_stop_cmd,
                },
                "derived": {
                    "arm_ack_ms": (t_armed_ack - t_arm_send) * 1000.0
                    if t_armed_ack is not None and t_arm_send is not None
                    else None,
                    "record_cmd_after_marker_ms": (t_record_cmd - t_marker) * 1000.0
                    if t_record_cmd is not None and t_marker is not None
                    else None,
                    "teensy_capture_after_marker_s": (t_capture_done - t_marker)
                    if t_capture_done is not None and t_marker is not None
                    else None,
                },
            },
            "streams": schema_streams,
            "files": {
                "teensy": {
                    "raw_bin": relative_path(raw_path, exp_dir) if args.teensy_enable else "",
                    "ch1_wav": relative_path(ch1_wav_path, exp_dir) if args.teensy_enable else "",
                    "ch2_wav": relative_path(ch2_wav_path, exp_dir) if args.teensy_enable else "",
                },
                "interface": {
                    "ch1_wav": relative_path(iface_channel_paths[0], exp_dir) if len(iface_channel_paths) > 0 else "",
                    "ch2_wav": relative_path(iface_channel_paths[1], exp_dir) if len(iface_channel_paths) > 1 else "",
                },
                "manifests": {
                    "trial_manifest": relative_path(manifest_path, exp_dir),
                    "trial_metadata": relative_path(schema_meta_path, exp_dir),
                },
            },
            "audacity": {
                "enabled": bool(args.audacity_import),
                "timeline_state_path": relative_path(Path(audacity_timeline.get("state_path", "")), exp_dir)
                if audacity_timeline.get("state_path")
                else "",
            },
            "experiment_profile_snapshot": experiment_profile,
        }

        audacity_teensy_ch1_path = ch1_wav_path
        audacity_teensy_ch2_path = ch2_wav_path
        if args.audacity_import and not args.teensy_enable:
            if len(iface_channel_paths) < 2:
                raise SystemExit("Interface-only Audacity import requires two interface channel WAV files")
            audacity_dir.mkdir(parents=True, exist_ok=True)
            audacity_teensy_ch1_path = audacity_dir / "_audacity_placeholder_teensy_ch1.wav"
            audacity_teensy_ch2_path = audacity_dir / "_audacity_placeholder_teensy_ch2.wav"
            write_silence_wav(audacity_teensy_ch1_path, iface_stats["duration_s"], args.iface_sample_rate)
            write_silence_wav(audacity_teensy_ch2_path, iface_stats["duration_s"], args.iface_sample_rate)

        audacity_timeline = update_audacity_timeline(
            args=args,
            orchestration_dir=orchestration_dir,
            audacity_dir=audacity_dir,
            iface_channel_paths=iface_channel_paths,
            ch1_wav_path=audacity_teensy_ch1_path,
            ch2_wav_path=audacity_teensy_ch2_path,
        )
        metadata["audacity_timeline"] = audacity_timeline
        manifest["audacity"] = audacity_timeline

        audacity_schema_block = {
            "enabled": bool(args.audacity_import),
            "timeline_state_path": relative_path(Path(audacity_timeline.get("state_path", "")), exp_dir)
            if audacity_timeline.get("state_path")
            else "",
            "project": {
                "path": relative_path(Path(audacity_timeline.get("project_path", "")), exp_dir)
                if audacity_timeline.get("project_path")
                else "",
            },
            "lifecycle_events": audacity_timeline.get("lifecycle_events", []),
        }
        audacity_status = str(audacity_timeline.get("status", "")).strip().lower()
        if audacity_status == "opened":
            audacity_schema_block["project"]["status"] = "opened"
        elif audacity_status == "failed":
            audacity_schema_block["project"]["status"] = "failed"
        elif audacity_status == "saved":
            audacity_schema_block["project"]["status"] = "saved"
        elif audacity_status == "created":
            audacity_schema_block["project"]["status"] = "created"
        trial_metadata_v2["audacity"] = audacity_schema_block
        if audacity_timeline.get("error"):
            trial_metadata_v2.setdefault("errors", []).append(
                {
                    "code": "AUDACITY_AUTOMATION_ERROR",
                    "message": str(audacity_timeline.get("error")),
                    "component": "audacity",
                }
            )

        schema_meta_path.write_text(json.dumps(trial_metadata_v2, indent=2), encoding="utf-8")
        metadata["schema_v2_path"] = str(schema_meta_path)
        stream_states["teensy"]["files"]["metadata_v2"] = str(schema_meta_path)

        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        write_trial_manifest(manifest_path, manifest)
        print(f"Saved capture artifacts in {trial_dir}")
        print(f"Saved trial manifest to {manifest_path}")

        if args.post_rigol:
            run_post_rigol_capture(args.experiment, args.trial)

    finally:
        if iface is not None and iface._stream is not None:
            try:
                iface.stop()
            except Exception:
                pass


if __name__ == "__main__":
    main()
