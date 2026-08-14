import argparse
import json
import os
import select
import serial
import shutil
import time
import wave
from pathlib import Path
from datetime import datetime

CMD_ARM = b"A"
CMD_STOP = b"T"
ARM_ACK = b"ARMED"
CAPTURE_MARKER = b"\xAA\x55"

DEFAULT_DURATION_S = 5
SAMPLE_RATE_HZ = 20000
CHANNELS = 2
ARM_ACK_TIMEOUT_S = 1.0
ARM_RETRY_COUNT = 5
AUDACITY_POST_STOP_DELAY_S = 0.35
AUDACITY_IMPORT_SPACING_S = 0.25
AUDACITY_POST_IMPORT_DELAY_S = 0.5
AUDACITY_COMMAND_SPACING_S = 0.35
AUDACITY_PRE_CLOSE_DELAY_S = 0.75
AUDACITY_PRE_IMPORT_DELAY_S = 1.0
AUDACITY_POST_STOP_QUERY_TIMEOUT_S = 0.6
AUDACITY_STOP_RETRIES = 3
AUDACITY_STOP_EXTRA_S = 0.0
INITIAL_IMPORT_OFFSET_S = 0.0
IMPORT_STATE_FILENAME = "teensy_import_segments.json"
IMPORT_BUFFER_FILENAME = "_teensy_import_buffer.wav"
IMPORT_SEGMENTS_DIRNAME = "_teensy_segments_ch1"
IMPORT_TRACK_INDEX = 2
IMPORT_TRACK_CLEANUP_PASSES = 12


class AudacityPipe:
    def __init__(self, timeout_s: float = 2.0, command_spacing_s: float = AUDACITY_COMMAND_SPACING_S):
        uid = os.getuid()
        self.to_path = Path(f"/tmp/audacity_script_pipe.to.{uid}")
        self.from_path = Path(f"/tmp/audacity_script_pipe.from.{uid}")
        self.timeout_s = timeout_s
        self.command_spacing_s = max(0.0, float(command_spacing_s))
        self.to_pipe = None
        self.from_pipe = None
        self._last_send_time = 0.0

    def open(self):
        if not self.to_path.exists() or not self.from_path.exists():
            raise RuntimeError(
                "Audacity mod-script-pipe not available. Open Audacity and enable mod-script-pipe."
            )
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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Arm Teensy capture, start/stop Audacity recording on button press, and import captured WAV."
    )
    parser.add_argument("--port", required=True, help="Serial port for Teensy")
    parser.add_argument("--output-dir", default="experiments", help="Base output directory")
    parser.add_argument("--experiment", default="TeensyCapture", help="Experiment title")
    parser.add_argument("--trial", type=int, default=1, help="Trial number")
    parser.add_argument("--duration", type=int, default=None, help="Capture duration in seconds")
    parser.add_argument(
        "--record-command",
        default="Record1stChoice",
        help="Audacity recording command (e.g., Record1stChoice or Record2ndChoice)",
    )
    parser.add_argument(
        "--skip-audacity",
        action="store_true",
        help="Skip Audacity control (for serial-capture-only testing)",
    )
    parser.add_argument(
        "--audacity-mode",
        choices=["record-stop-import-ch1", "record-stop", "import-ch1-only"],
        default="record-stop-import-ch1",
        help="Choose which Audacity actions to run for crash isolation.",
    )
    parser.add_argument(
        "--post-stop-delay",
        type=float,
        default=AUDACITY_POST_STOP_DELAY_S,
        help="Seconds to wait after Stop before any import command.",
    )
    parser.add_argument(
        "--audacity-stop-extra-s",
        type=float,
        default=AUDACITY_STOP_EXTRA_S,
        help="Extra seconds to keep Audacity recording after Teensy capture completes.",
    )
    parser.add_argument(
        "--import-spacing",
        type=float,
        default=AUDACITY_IMPORT_SPACING_S,
        help="Seconds to wait between Audacity import-related commands.",
    )
    parser.add_argument(
        "--reopen-pipe-before-import",
        action="store_true",
        default=False,
        help="Reopen mod-script-pipe before import when combining record/stop+import.",
    )
    parser.add_argument(
        "--no-reopen-pipe-before-import",
        dest="reopen_pipe_before_import",
        action="store_false",
        help="Do not reopen mod-script-pipe before import.",
    )
    parser.add_argument(
        "--post-import-delay",
        type=float,
        default=AUDACITY_POST_IMPORT_DELAY_S,
        help="Seconds to wait after import before exiting the script.",
    )
    parser.add_argument(
        "--audacity-command-spacing",
        type=float,
        default=AUDACITY_COMMAND_SPACING_S,
        help="Minimum seconds between any two Audacity pipe commands.",
    )
    parser.add_argument(
        "--pre-close-delay",
        type=float,
        default=AUDACITY_PRE_CLOSE_DELAY_S,
        help="Seconds to wait before closing the Audacity pipe at shutdown.",
    )
    parser.add_argument(
        "--pre-import-delay",
        type=float,
        default=AUDACITY_PRE_IMPORT_DELAY_S,
        help="Seconds to wait just before sending Import2.",
    )
    parser.add_argument(
        "--initial-import-offset-s",
        type=float,
        default=INITIAL_IMPORT_OFFSET_S,
        help="Applied only when the first segment anchor is 0.0 (playhead metadata unavailable).",
    )
    parser.add_argument(
        "--skip-track-removal",
        action="store_true",
        default=False,
        help="Do not issue track removal commands (safer for Audacity stability).",
    )
    parser.add_argument(
        "--allow-track-removal",
        dest="skip_track_removal",
        action="store_false",
        help="Allow track removal commands before re-import.",
    )
    parser.add_argument(
        "--leave-audacity-pipe-open",
        action="store_true",
        default=True,
        help="Skip explicit pipe close at shutdown (lets Audacity settle on process exit).",
    )
    parser.add_argument(
        "--close-audacity-pipe",
        dest="leave_audacity_pipe_open",
        action="store_false",
        help="Explicitly close the Audacity pipe at shutdown.",
    )
    parser.add_argument(
        "--reset-import-history",
        action="store_true",
        help="Clear consolidated import state and snapshot files before this run.",
    )
    parser.add_argument(
        "--auto-reset-on-trial-one",
        action="store_true",
        default=True,
        help="Automatically reset import history when --trial 1 is used.",
    )
    parser.add_argument(
        "--no-auto-reset-on-trial-one",
        dest="auto_reset_on_trial_one",
        action="store_false",
        help="Do not automatically reset import history on trial 1.",
    )
    parser.add_argument(
        "--auto-reset-on-empty-project",
        action="store_true",
        default=False,
        help="Reset import history if Audacity project appears empty (excluding import track).",
    )
    parser.add_argument(
        "--no-auto-reset-on-empty-project",
        dest="auto_reset_on_empty_project",
        action="store_false",
        help="Do not reset import history when project appears empty.",
    )
    parser.add_argument(
        "--post-stop-query-timeout",
        type=float,
        default=AUDACITY_POST_STOP_QUERY_TIMEOUT_S,
        help="Seconds allowed for optional post-stop metadata probe.",
    )
    parser.add_argument(
        "--skip-post-stop-probe",
        action="store_true",
        default=True,
        help="Do not query Audacity metadata after Stop (prevents hangs on some builds).",
    )
    parser.add_argument(
        "--enable-post-stop-probe",
        dest="skip_post_stop_probe",
        action="store_false",
        help="Enable post-stop metadata probe to refine start-time estimate.",
    )
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


def wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


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


def audacity_quote(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace('"', '\\"')


def wait_for_file_ready(path: Path, min_bytes: int = 44, timeout_s: float = 2.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if path.exists() and path.stat().st_size >= min_bytes:
            return True
        time.sleep(0.05)
    return path.exists() and path.stat().st_size >= min_bytes


def extract_first_json_blob(text: str):
    starts = [idx for idx in (text.find("{"), text.find("[")) if idx != -1]
    if not starts:
        return None
    start = min(starts)
    end_obj = text.rfind("}")
    end_arr = text.rfind("]")
    end = max(end_obj, end_arr)
    if end < start:
        return None
    blob = text[start : end + 1]
    try:
        return json.loads(blob)
    except json.JSONDecodeError:
        return None


def audacity_track_list(audacity: AudacityPipe, timeout_s: float = 5.0):
    # In Audacity 3.7.x, Clips is the most reliable source of wave-track timing data.
    resp = audacity.send("GetInfo: Type=Clips Format=JSON", timeout_s=timeout_s)
    data = extract_first_json_blob(resp)
    if isinstance(data, list):
        return data
    return []


def clip_end_by_name(tracks):
    out = {}
    for track in tracks:
        if not isinstance(track, dict):
            continue
        name = str(track.get("name", ""))
        end = _track_end_seconds(track)
        if not name or end is None:
            continue
        out[name] = max(out.get(name, 0.0), end)
    return out


def infer_record_start_seconds(before_tracks, after_tracks, duration_seconds: int) -> float | None:
    before_ends = clip_end_by_name(before_tracks)
    candidates = []
    min_growth = max(0.5, duration_seconds * 0.60)

    for track in after_tracks:
        if not isinstance(track, dict):
            continue
        kind = str(track.get("kind", ""))
        if kind and kind != "wave":
            continue

        name = str(track.get("name", ""))
        end = _track_end_seconds(track)
        if end is None:
            continue

        before_end = before_ends.get(name)
        if before_end is None:
            # New recording track: infer from its end and known duration.
            candidates.append(max(0.0, end - float(duration_seconds)))
            continue

        growth = end - before_end
        if growth >= min_growth:
            candidates.append(max(0.0, end - float(duration_seconds)))

    if not candidates:
        return None
    return min(candidates)


def _track_end_seconds(track) -> float | None:
    if not isinstance(track, dict):
        return None
    end = track.get("end")
    if isinstance(end, (int, float)):
        return float(end)
    start = track.get("start")
    if isinstance(start, (int, float)):
        if isinstance(track.get("len"), (int, float)):
            return float(start) + float(track["len"])
        if isinstance(track.get("length"), (int, float)):
            return float(start) + float(track["length"])
    return None


def audacity_project_end_seconds(audacity: AudacityPipe) -> float:
    ends = []
    for track in audacity_track_list(audacity):
        end = _track_end_seconds(track)
        if end is not None:
            ends.append(end)
    return max(ends) if ends else 0.0


def audacity_project_end_seconds_excluding_names(audacity: AudacityPipe, excluded_names: set[str]) -> float:
    ends = []
    for track in audacity_track_list(audacity):
        if isinstance(track, dict) and str(track.get("name", "")) in excluded_names:
            continue
        end = _track_end_seconds(track)
        if end is not None:
            ends.append(end)
    return max(ends) if ends else 0.0


def find_track_indices_by_name(tracks, name: str):
    indices = []
    for idx, track in enumerate(tracks):
        if isinstance(track, dict) and str(track.get("name", "")) == name:
            indices.append(idx)
    return indices


def audacity_paste_import_onto_existing_track(
    audacity: AudacityPipe,
    target_track_idx: int,
    source_track_idx: int,
    paste_time_s: float,
    spacing_s: float,
):
    # Copy full clip from imported temporary track.
    audacity.send(f"SelectTracks: Track={source_track_idx} TrackCount=1 Mode=Set")
    audacity.send("SelTrackStartToEnd")
    audacity.send("Copy")
    time.sleep(max(0.0, spacing_s))

    # Paste at the capture start time into the persistent mono track.
    audacity.send(f"SelectTracks: Track={target_track_idx} TrackCount=1 Mode=Set")
    audacity.send(
        f"SelectTime: Start={paste_time_s:.6f} End={paste_time_s:.6f} RelativeTo=ProjectStart"
    )
    audacity.send("Paste")
    time.sleep(max(0.0, spacing_s))

    # Remove temporary imported track so one mono timeline track remains.
    audacity.send(f"SelectTracks: Track={source_track_idx} TrackCount=1 Mode=Set")
    audacity.send("RemoveTracks")


def remove_tracks_by_name(audacity: AudacityPipe, names: set[str]):
    tracks = audacity_track_list(audacity)
    # Remove in reverse order so indices remain valid while deleting.
    indexed = list(enumerate(tracks))
    for idx, track in reversed(indexed):
        track_name = ""
        if isinstance(track, dict):
            track_name = str(track.get("name", ""))
        if track_name in names:
            audacity.send(f"SelectTracks: Track={idx} TrackCount=1 Mode=Set")
            audacity.send("RemoveTracks")
            time.sleep(AUDACITY_IMPORT_SPACING_S)


def remove_tracks_from_index(audacity: AudacityPipe, start_index: int, passes: int, spacing_s: float):
    # Repeatedly remove the track at a fixed index; higher tracks shift down each pass.
    for _ in range(max(0, passes)):
        audacity.send(f"SelectTracks: Track={start_index} TrackCount=1 Mode=Set")
        audacity.send("RemoveTracks")
        time.sleep(max(0.0, spacing_s))


def append_mono_wav(dest_path: Path, new_pcm: bytes, sample_rate: int):
    if not dest_path.exists():
        write_wav(dest_path, new_pcm, sample_rate, channels=1)
        return

    with wave.open(str(dest_path), "rb") as existing:
        if existing.getnchannels() != 1 or existing.getsampwidth() != 2:
            raise RuntimeError(f"Unexpected WAV format in {dest_path}")
        if existing.getframerate() != sample_rate:
            raise RuntimeError(f"Sample rate mismatch in {dest_path}")
        old_frames = existing.readframes(existing.getnframes())

    with wave.open(str(dest_path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(sample_rate)
        out.writeframes(old_frames)
        out.writeframes(new_pcm)


def read_mono_wav_pcm(path: Path, sample_rate: int) -> bytes:
    with wave.open(str(path), "rb") as wf:
        if wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            raise RuntimeError(f"Expected mono 16-bit WAV: {path}")
        if wf.getframerate() != sample_rate:
            raise RuntimeError(f"Sample rate mismatch in {path}")
        return wf.readframes(wf.getnframes())


def load_import_segments(state_path: Path):
    if not state_path.exists():
        return []
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if not isinstance(item, dict):
            continue
        file_path = item.get("file")
        start_seconds = item.get("start_seconds")
        if not isinstance(file_path, str):
            continue
        if not isinstance(start_seconds, (int, float)):
            continue
        out.append({"file": file_path, "start_seconds": float(start_seconds)})
    return out


def sanitize_import_segments(segments, stale_name: str):
    # Old state stored trial paths that get overwritten each run; drop those to avoid self-copy artifacts.
    cleaned = []
    seen = set()
    for seg in segments:
        file_path = Path(seg.get("file", ""))
        if file_path.name == stale_name:
            continue
        if not file_path.exists():
            continue
        file_key = str(file_path.resolve())
        if file_key in seen:
            continue
        seen.add(file_key)
        cleaned.append({
            "file": file_key,
            "start_seconds": float(seg.get("start_seconds", 0.0)),
            "trial": int(seg.get("trial", 0)) if str(seg.get("trial", "")).isdigit() else 0,
        })
    return cleaned


def max_segment_end_seconds(segments, sample_rate: int) -> float:
    max_end = 0.0
    for seg in segments:
        p = Path(seg.get("file", ""))
        if not p.exists():
            continue
        try:
            with wave.open(str(p), "rb") as w:
                dur = w.getnframes() / w.getframerate()
        except (wave.Error, OSError):
            continue
        start = float(seg.get("start_seconds", 0.0))
        max_end = max(max_end, start + dur)
    return max_end


def replace_or_append_trial_segment(segments, trial_number: int, new_segment: dict):
    out = [s for s in segments if int(s.get("trial", -1)) != int(trial_number)]
    out.append(new_segment)
    return out


def reset_import_history(exp_dir: Path):
    state_path = exp_dir / IMPORT_STATE_FILENAME
    buffer_path = exp_dir / IMPORT_BUFFER_FILENAME
    segments_dir = exp_dir / IMPORT_SEGMENTS_DIRNAME
    if state_path.exists():
        state_path.unlink()
    if buffer_path.exists():
        buffer_path.unlink()
    if segments_dir.exists():
        shutil.rmtree(segments_dir)


def save_import_segments(state_path: Path, segments):
    state_path.write_text(json.dumps(segments, indent=2), encoding="utf-8")


def build_import_buffer_wav(segments, out_path: Path, sample_rate: int):
    timeline = bytearray()
    for seg in sorted(segments, key=lambda s: s["start_seconds"]):
        wav_path = Path(seg["file"])
        if not wav_path.exists():
            continue
        pcm = read_mono_wav_pcm(wav_path, sample_rate)
        start_samples = int(round(max(0.0, float(seg["start_seconds"])) * sample_rate))
        start_bytes = start_samples * 2
        end_bytes = start_bytes + len(pcm)

        if len(timeline) < start_bytes:
            timeline.extend(b"\x00" * (start_bytes - len(timeline)))
        if len(timeline) < end_bytes:
            timeline.extend(b"\x00" * (end_bytes - len(timeline)))

        # Overwrite range so each segment lands at its intended absolute project time.
        timeline[start_bytes:end_bytes] = pcm

    if not timeline:
        # Always emit a valid mono WAV so import command has a concrete file.
        write_wav(out_path, b"", sample_rate, channels=1)
        return
    write_wav(out_path, bytes(timeline), sample_rate, channels=1)


def snapshot_segment_file(source_wav: Path, segments_dir: Path, trial_number: int) -> Path:
    segments_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    out_path = segments_dir / f"trial{trial_number}_{stamp}_ch1.wav"
    out_path.write_bytes(source_wav.read_bytes())
    return out_path


def send_audacity_stop(audacity: AudacityPipe, retries: int, spacing_s: float):
    for _ in range(max(1, retries)):
        audacity.send("Stop")
        time.sleep(max(0.0, spacing_s))


def dbg(msg: str):
    print(f"[DBG] {msg}")


def main():
    args = parse_args()
    duration_seconds = args.duration if args.duration is not None else prompt_duration(DEFAULT_DURATION_S)

    exp_dir = Path(args.output_dir) / safe_name(args.experiment)
    trial_dir = exp_dir / f"trial_{args.trial}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    if args.reset_import_history or (args.auto_reset_on_trial_one and args.trial == 1):
        reset_import_history(exp_dir)

    metadata = {
        "experiment_title": args.experiment,
        "trial_number": args.trial,
        "duration_seconds": duration_seconds,
        "sample_rate_hz": SAMPLE_RATE_HZ,
        "channels": CHANNELS,
        "capture_time": datetime.now().isoformat(),
        "audacity_record_command": args.record_command,
    }

    raw_path = trial_dir / "teensy_stream.bin"
    stereo_wav_path = trial_dir / "teensy_stream.wav"
    ch1_wav_path = trial_dir / "teensy_stream_Ch1.wav"
    ch2_wav_path = trial_dir / "teensy_stream_ch2.wav"
    meta_path = trial_dir / "teensy_capture_metadata.json"

    audacity = None
    if not args.skip_audacity:
        audacity = AudacityPipe(timeout_s=3.0, command_spacing_s=args.audacity_command_spacing)
        audacity.open()

    try:
        with serial.Serial(args.port, 2000000, timeout=1, dsrdtr=False, rtscts=False, xonxoff=False) as ser:
            time.sleep(0.5)
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            arm_command = CMD_ARM + bytes([duration_seconds])
            armed = False
            leftover = b""
            t_arm_send = None
            t_armed_ack = None
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
            started, leftover = read_until_marker(ser, CAPTURE_MARKER, timeout=None)
            t_marker = time.time()
            if not started:
                raise SystemExit("Failed waiting for capture start marker")

            do_record_stop = args.audacity_mode in {"record-stop-import-ch1", "record-stop"}
            do_import = args.audacity_mode in {"record-stop-import-ch1", "import-ch1-only"}

            record_start_time_s = 0.0
            t_record_cmd = None

            if audacity is not None and do_record_stop:
                # Use project end before record as a stable per-run placement anchor.
                record_start_time_s = audacity_project_end_seconds_excluding_names(
                    audacity,
                    excluded_names={IMPORT_BUFFER_FILENAME.rsplit(".", 1)[0]},
                )
                t_record_cmd = time.time()
                audacity.send(args.record_command)
                print("Audacity recording started")

            total_samples = duration_seconds * SAMPLE_RATE_HZ
            total_bytes = total_samples * CHANNELS * 2
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

        if audacity is not None and do_record_stop:
            if args.audacity_stop_extra_s > 0.0:
                time.sleep(max(0.0, args.audacity_stop_extra_s))
            t_stop_cmd = time.time()
            audacity.send("Stop")
            print("Audacity recording stopped")
            time.sleep(max(0.0, args.post_stop_delay))

        if audacity is not None and do_record_stop and do_import and args.reopen_pipe_before_import:
            # Reopening the pipe between Stop and Import avoids a known end-of-run instability.
            audacity.close()
            time.sleep(max(0.0, args.import_spacing))
            audacity.open()

        raw_path.write_bytes(buffer)
        write_wav(stereo_wav_path, bytes(buffer), SAMPLE_RATE_HZ, channels=2)
        ch_bytes = extract_channels(bytes(buffer), channels=2)
        write_wav(ch1_wav_path, ch_bytes[0], SAMPLE_RATE_HZ, channels=1)
        write_wav(ch2_wav_path, ch_bytes[1], SAMPLE_RATE_HZ, channels=1)

        # Debug timing summary for serial and record/stop correlation.
        if t_arm_send is not None and t_armed_ack is not None:
            dbg(f"arm_ack_ms={(t_armed_ack - t_arm_send) * 1000.0:.1f}")
        dbg(f"wait_for_marker_s={(t_marker - t_wait_marker):.3f}")
        if t_record_cmd is not None:
            dbg(f"audacity_record_lag_from_marker_ms={(t_record_cmd - t_marker) * 1000.0:.1f}")
        dbg(f"capture_read_after_marker_s={(t_capture_done - t_marker):.3f}")
        if audacity is not None and do_record_stop:
            dbg(f"audacity_stop_after_marker_s={(t_stop_cmd - t_marker):.3f}")
            dbg(f"audacity_stop_extra_s={max(0.0, args.audacity_stop_extra_s):.3f}")
        dbg(
            "trial_wav_durations_s="
            f"ch1:{wav_duration_seconds(ch1_wav_path):.3f},"
            f"ch2:{wav_duration_seconds(ch2_wav_path):.3f},"
            f"stereo:{wav_duration_seconds(stereo_wav_path):.3f}"
        )

        if audacity is not None and do_import:
            ch1_abs = ch1_wav_path.resolve()
            if not wait_for_file_ready(ch1_abs):
                raise SystemExit("CH1 WAV file was not ready for Audacity import")

            state_path = exp_dir / IMPORT_STATE_FILENAME
            import_buffer_path = exp_dir / IMPORT_BUFFER_FILENAME
            segments_dir = exp_dir / IMPORT_SEGMENTS_DIRNAME

            segments = load_import_segments(state_path)
            segments = sanitize_import_segments(segments, stale_name=ch1_wav_path.name)
            segment_snapshot = snapshot_segment_file(ch1_abs, segments_dir, args.trial)

            # Use pre-record anchor when available; otherwise append after current consolidated end.
            if record_start_time_s > 0.001:
                segment_start_s = float(record_start_time_s)
            else:
                segment_start_s = max_segment_end_seconds(segments, SAMPLE_RATE_HZ)
                if segment_start_s <= 0.001 and args.initial_import_offset_s != 0.0:
                    segment_start_s = max(0.0, float(args.initial_import_offset_s))

            segments = replace_or_append_trial_segment(
                segments,
                trial_number=args.trial,
                new_segment={
                    "trial": int(args.trial),
                    "file": str(segment_snapshot.resolve()),
                    "start_seconds": segment_start_s,
                },
            )
            save_import_segments(state_path, segments)
            build_import_buffer_wav(segments, import_buffer_path, SAMPLE_RATE_HZ)
            buffer_dur_s = wav_duration_seconds(import_buffer_path)

            # Keep a single import track by clearing tracks >= index 2 before import.
            if not args.skip_track_removal:
                remove_tracks_from_index(
                    audacity,
                    start_index=IMPORT_TRACK_INDEX,
                    passes=IMPORT_TRACK_CLEANUP_PASSES,
                    spacing_s=args.import_spacing,
                )
                time.sleep(max(0.0, args.import_spacing))

            time.sleep(max(0.0, args.pre_import_delay))
            import_cmd = f'Import2: Filename="{audacity_quote(import_buffer_path.resolve())}"'
            audacity.send(import_cmd, timeout_s=5.0)
            print(
                f"Imported consolidated CH1 track ({len(segments)} segments), latest at {segment_start_s:.3f}s"
            )
            dbg(
                f"import_state=trial:{args.trial},segment_start_s:{segment_start_s:.3f},"
                f"segment_dur_s:{wav_duration_seconds(segment_snapshot):.3f},"
                f"consolidated_buffer_dur_s:{buffer_dur_s:.3f},segments:{len(segments)}"
            )

            time.sleep(max(0.0, args.post_import_delay))

        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(f"Saved capture artifacts in {trial_dir}")

    finally:
        if audacity is not None:
            time.sleep(max(0.0, args.pre_close_delay))
            if not args.leave_audacity_pipe_open:
                audacity.close()


if __name__ == "__main__":
    main()
