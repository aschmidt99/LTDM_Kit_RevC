import argparse
import json
import os
import select
import time
from datetime import datetime
from pathlib import Path

import serial

CMD_ARM = b"A"
CMD_STOP = b"T"
ARM_ACK = b"ARMED"
CAPTURE_MARKER = b"\xAA\x55"

DEFAULT_DURATION_S = 5
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


def parse_args():
    parser = argparse.ArgumentParser(
        description="Phase 1: capture Teensy stream and audio-interface input in one Python run."
    )
    parser.add_argument("--port", required=True, help="Serial port for Teensy")
    parser.add_argument("--output-dir", default="experiments", help="Base output directory")
    parser.add_argument("--experiment", default="TeensyCapture", help="Experiment title")
    parser.add_argument("--trial", type=int, default=1, help="Trial number")
    parser.add_argument("--duration", type=int, default=None, help="Capture duration in seconds")

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
        "--audacity-reset-timeline",
        action="store_true",
        help="Reset Audacity timeline state for this experiment before appending this trial.",
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
    if seconds <= 0 or seconds > 60:
        raise SystemExit("Capture duration must be between 1 and 60 seconds")
    return seconds


def dbg(msg: str):
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


def save_interface_wav_channels(data, sample_rate: int, trial_dir: Path, channels: int, subtype: str = "PCM_16"):
    import soundfile as sf

    out_paths = []
    channel_count = min(channels, data.shape[1])
    for ch in range(channel_count):
        out_path = trial_dir / f"interface_capture_ch{ch + 1}.wav"
        sf.write(str(out_path), data[:, ch], sample_rate, subtype=subtype)
        out_paths.append(out_path)
    return out_paths


def main():
    args = parse_args()

    if args.iface_list_devices:
        InterfaceRecorder.list_devices()
        return

    duration_seconds = args.duration if args.duration is not None else prompt_duration(DEFAULT_DURATION_S)

    exp_dir = Path(args.output_dir) / safe_name(args.experiment)
    trial_dir = exp_dir / f"trial_{args.trial}"
    trial_dir.mkdir(parents=True, exist_ok=True)

    raw_path = trial_dir / "teensy_stream.bin"
    ch1_wav_path = trial_dir / "teensy_stream_Ch1.wav"
    ch2_wav_path = trial_dir / "teensy_stream_ch2.wav"
    meta_path = trial_dir / "teensy_interface_capture_metadata.json"

    iface = None
    if args.iface_enable:
        iface = InterfaceRecorder(
            device=args.iface_device,
            channels=args.iface_channels,
            sample_rate=args.iface_sample_rate,
        )
        iface.setup()

    t_record_cmd = None
    t_marker = None
    t_capture_done = None
    t_stop_cmd = None

    try:
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

            if iface is not None and args.iface_start_mode == "marker":
                iface.start()
                dbg(
                    f"iface_start=device:{args.iface_device},sr:{args.iface_sample_rate},"
                    f"ch:{args.iface_channels},mode:marker,t0:{iface.started_at:.6f},"
                    f"after_marker_ms={(iface.started_at - t_marker) * 1000.0:.1f}"
                )

            t_record_cmd = time.time()

            total_samples = duration_seconds * TEENSY_SAMPLE_RATE_HZ
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

            if args.iface_start_mode == "arm-gated" and iface.started_at is not None:
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

            if args.iface_auto_align and iface_data.shape[0] > 0:
                align_ch_idx = max(0, min(args.iface_channels - 1, args.iface_align_channel - 1))
                teensy_ch1_i16 = ch_bytes[0]
                if teensy_ch1_i16:
                    import numpy as np

                    lag_teensy_samples, align_score = estimate_interface_lag_samples(
                        teensy_ch1_i16=np.frombuffer(teensy_ch1_i16, dtype=np.int16),
                        teensy_sr=TEENSY_SAMPLE_RATE_HZ,
                        iface_ref_i16=iface_data[:, align_ch_idx],
                        iface_sr=args.iface_sample_rate,
                        max_offset_s=args.iface_align_max_offset_s,
                        envelope_ms=args.iface_align_envelope_ms,
                        analysis_hz=args.iface_align_analysis_hz,
                    )
                    lag_iface_samples = int(
                        round(lag_teensy_samples * float(args.iface_sample_rate) / float(TEENSY_SAMPLE_RATE_HZ))
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

            if args.iface_trim_to_teensy and iface_data.shape[0] > 0:
                teensy_samples = len(ch_bytes[0]) // 2
                target_iface_samples = int(
                    round(teensy_samples * float(args.iface_sample_rate) / float(TEENSY_SAMPLE_RATE_HZ))
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
                trial_dir=trial_dir,
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

        raw_path.write_bytes(buffer)
        write_wav(ch1_wav_path, ch_bytes[0], TEENSY_SAMPLE_RATE_HZ, channels=1)
        write_wav(ch2_wav_path, ch_bytes[1], TEENSY_SAMPLE_RATE_HZ, channels=1)

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

        # Maintain per-trial timeline state and optionally push 4 fixed tracks into Audacity.
        audacity_timeline = {
            "enabled": bool(args.audacity_import),
            "state_path": str(exp_dir / AUDACITY_STATE_FILENAME),
            "records": 0,
            "latest_start_s": 0.0,
            "latest_end_s": 0.0,
        }
        if args.audacity_import:
            if not iface_channel_paths or len(iface_channel_paths) < 2:
                raise SystemExit("Audacity import requires interface_capture_ch1.wav and interface_capture_ch2.wav")

            state_path = exp_dir / AUDACITY_STATE_FILENAME
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
            audacity.open()
            try:
                do_full_rebuild = bool(args.audacity_reset_timeline) or prior_records_count == 0 or (not is_new_trial)
                if do_full_rebuild:
                    import_records_to_audacity(
                        audacity,
                        records,
                        playhead_s=latest_end_s,
                        reset_passes=max(1, int(args.audacity_reset_passes)),
                        pre_import_delay_s=max(0.0, float(args.audacity_pre_import_delay)),
                        post_import_delay_s=max(0.0, float(args.audacity_post_import_delay)),
                    )
                else:
                    append_record_to_audacity(
                        audacity,
                        trial_rec,
                        playhead_s=latest_end_s,
                        pre_import_delay_s=max(0.0, float(args.audacity_pre_import_delay)),
                        post_import_delay_s=max(0.0, float(args.audacity_post_import_delay)),
                    )
            finally:
                audacity.close()

            dbg(
                f"audacity_timeline=records:{len(records)},latest_start_s:{trial_rec['start_s']:.3f},"
                f"latest_end_s:{latest_end_s:.3f},next_start_s:{next_start_s:.3f}"
            )

            audacity_timeline = {
                "enabled": True,
                "state_path": str(state_path),
                "records": len(records),
                "latest_start_s": float(trial_rec["start_s"]),
                "latest_end_s": float(latest_end_s),
                "next_start_s": float(next_start_s),
                "import_mode": "per-trial-clips-4-tracks",
                "rebuild_mode": bool(do_full_rebuild),
            }

        metadata = {
            "experiment_title": args.experiment,
            "trial_number": args.trial,
            "duration_seconds": duration_seconds,
            "capture_time": datetime.now().isoformat(),
            "teensy": {
                "port": args.port,
                "sample_rate_hz": TEENSY_SAMPLE_RATE_HZ,
                "channels": TEENSY_CHANNELS,
            },
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
                "record_cmd_after_marker_ms": (t_record_cmd - t_marker) * 1000.0,
                "teensy_capture_after_marker_s": (t_capture_done - t_marker),
            },
            "files": {
                "raw": str(raw_path),
                "teensy_ch1_wav": str(ch1_wav_path),
                "teensy_ch2_wav": str(ch2_wav_path),
            },
            "audacity_timeline": audacity_timeline,
        }

        meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(f"Saved capture artifacts in {trial_dir}")

    finally:
        if iface is not None and iface._stream is not None:
            try:
                iface.stop()
            except Exception:
                pass


if __name__ == "__main__":
    main()
