#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

from core.experiment_profile import prompt_profile_field_changes
from core.path_layout import build_experiment_paths, existing_trial_numbers
from core.trial_metadata import get_reference_trial_metadata

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = str(BASE_DIR / "experiments")
CAPTURE_SCRIPT = BASE_DIR / "capture" / "teensy_plus_interface.py"
RIGOL_SCRIPT = BASE_DIR / "rigol" / "capture.py"
CAPTURE_MODULE = "capture.teensy_plus_interface"
RIGOL_MODULE = "rigol.capture"
STATE_FILENAME = "audacity_timeline_state.json"

DEFAULT_PORT = "/dev/cu.usbmodem199934501"
DEFAULT_IFACE_DEVICE = "6"
DEFAULT_IFACE_SAMPLE_RATE = "192000"
DEFAULT_IFACE_CHANNELS = "2"
DEFAULT_IFACE_START_MODE = "arm-gated"
DEFAULT_IFACE_PRE_ROLL = "0.05"
DEFAULT_IFACE_POST_ROLL = "0.05"
DEFAULT_AUDACITY_COMMAND_SPACING = "0.25"
DEFAULT_AUDACITY_RESET_PASSES = "3"
DEFAULT_AUDACITY_PRE_IMPORT_DELAY = "0.10"
DEFAULT_AUDACITY_POST_IMPORT_DELAY = "0.10"
DEFAULT_AUDACITY_PRE_SAVE_DELAY = "1.00"
DEFAULT_AUDACITY_POST_SAVE_DELAY = "1.00"
DEFAULT_DURATION_S = 5
DEFAULT_PROFILE = "teensy_interface_no_audacity"

PROFILE_SETTINGS = {
    "interface_audacity": {
        "teensy": False,
        "interface": True,
        "audacity": True,
        "rigol": False,
        "description": "Interface recording only, with Audacity import.",
    },
    "interface_no_audacity": {
        "teensy": False,
        "interface": True,
        "audacity": False,
        "rigol": False,
        "description": "Interface recording only, without Audacity import.",
    },
    "rigol_only": {
        "teensy": False,
        "interface": False,
        "audacity": False,
        "rigol": True,
        "description": "Rigol capture only for the selected experiment/trial.",
    },
    "teensy_interface_audacity": {
        "teensy": True,
        "interface": True,
        "audacity": True,
        "rigol": False,
        "description": "Teensy + interface recording, with Audacity import.",
    },
    "teensy_interface_no_audacity": {
        "teensy": True,
        "interface": True,
        "audacity": False,
        "rigol": False,
        "description": "Teensy + interface recording, without Audacity import.",
    },
    "full_stack_audacity": {
        "teensy": True,
        "interface": True,
        "audacity": True,
        "rigol": True,
        "description": "Teensy + interface + Audacity + Rigol.",
    },
    "full_stack_no_audacity": {
        "teensy": True,
        "interface": True,
        "audacity": False,
        "rigol": True,
        "description": "Teensy + interface + Rigol, without Audacity import.",
    },
}


def parse_args():
    parser = argparse.ArgumentParser(description="Prompted LTDM trial runner.")
    parser.add_argument("--experiment", help="Experiment name/title")
    parser.add_argument("--trial", type=int, help="Trial number override")
    parser.add_argument("--duration", type=int, help="Duration override (seconds)")
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_SETTINGS.keys()),
        help="Capture profile to run",
    )
    parser.add_argument(
        "--audacity-pre-save-delay",
        type=float,
        default=float(DEFAULT_AUDACITY_PRE_SAVE_DELAY),
        help="Extra settle time before saving Audacity project.",
    )
    parser.add_argument(
        "--audacity-post-save-delay",
        type=float,
        default=float(DEFAULT_AUDACITY_POST_SAVE_DELAY),
        help="Extra settle time after saving Audacity project.",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip required device connection checks before metadata prompts/capture.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Check required devices for the selected profile, then exit before metadata prompts/capture.",
    )
    parser.add_argument("--debug", action="store_true", help="Enable verbose [DBG] diagnostics in capture script output")
    return parser.parse_args()


def state_path_for(experiment: str) -> Path:
    return build_experiment_paths(OUTPUT_DIR, experiment)["orchestration_dir"] / STATE_FILENAME


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def suggest_trial_and_duration(state: dict) -> tuple[int, int, set[int]]:
    records = state.get("records", [])
    if not isinstance(records, list):
        records = []

    trials: set[int] = set()
    last_duration = None

    for rec in records:
        if not isinstance(rec, dict):
            continue
        trial = rec.get("trial")
        duration_s = rec.get("duration_s")
        if isinstance(trial, int) and trial > 0:
            trials.add(trial)
        if isinstance(duration_s, (int, float)) and duration_s > 0:
            last_duration = int(max(1, round(float(duration_s))))

    suggested_trial = (max(trials) + 1) if trials else 1
    suggested_duration = last_duration if last_duration is not None else DEFAULT_DURATION_S
    return suggested_trial, suggested_duration, trials


def suggest_duration_for_trial(experiment: str, trial: int, fallback: int) -> int:
    reference = get_reference_trial_metadata(OUTPUT_DIR, experiment, trial)
    if isinstance(reference, dict):
        duration_seconds = reference.get("duration_seconds")
        if isinstance(duration_seconds, (int, float)) and duration_seconds > 0:
            return int(max(1, round(float(duration_seconds))))

    return int(max(1, fallback))


def prompt_text(prompt: str, default: str | None = None) -> str:
    import questionary

    raw = questionary.text(prompt, default=default or "").ask()
    value = "" if raw is None else str(raw).strip()
    if value:
        return value
    if default is not None:
        return str(default)
    raise SystemExit(f"{prompt} cannot be empty")


def prompt_int(prompt: str, default: int, min_value: int = 1) -> int:
    import questionary

    while True:
        raw = questionary.text(prompt, default=str(default)).ask()
        text = str(default).strip() if raw is None or str(raw).strip() == "" else str(raw).strip()
        try:
            value = int(text)
        except ValueError:
            print("Please enter an integer.")
            continue
        if value < min_value:
            print(f"Please enter a value >= {min_value}.")
            continue
        return value


def prompt_choice(prompt: str, options: list[str], default: str) -> str:
    default_text = f" [{default}]"
    while True:
        raw = input(f"{prompt}{default_text}: ").strip()
        if raw == "":
            return default
        if raw in options:
            return raw
        print(f"Please choose one of: {', '.join(options)}")


def resolve_profile(args) -> str:
    options = sorted(PROFILE_SETTINGS.keys())
    if args.profile:
        return args.profile

    print("\nAvailable profiles:")
    for name in options:
        print(f"  - {name}: {PROFILE_SETTINGS[name]['description']}")
    return prompt_choice("Profile", options, DEFAULT_PROFILE)


def suggest_last_experiment(output_dir: str) -> str | None:
    base = Path(output_dir)
    if not base.exists() or not base.is_dir():
        return None

    candidates = [p for p in base.iterdir() if p.is_dir() and not p.name.startswith(".")]
    if not candidates:
        return None

    try:
        latest = max(candidates, key=lambda p: p.stat().st_mtime)
    except Exception:
        return None
    return latest.name


def build_capture_command(
    experiment: str,
    trial: int,
    duration_s: int,
    teensy: bool,
    interface: bool,
    audacity: bool,
    rigol: bool,
    debug: bool,
    audacity_pre_save_delay: float,
    audacity_post_save_delay: float,
) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        CAPTURE_MODULE,
        "--port",
        DEFAULT_PORT,
        "--output-dir",
        OUTPUT_DIR,
        "--experiment",
        experiment,
        "--trial",
        str(trial),
        "--duration",
        str(duration_s),
        "--iface-device",
        DEFAULT_IFACE_DEVICE,
        "--iface-sample-rate",
        DEFAULT_IFACE_SAMPLE_RATE,
        "--iface-channels",
        DEFAULT_IFACE_CHANNELS,
        "--iface-start-mode",
        DEFAULT_IFACE_START_MODE,
        "--iface-pre-roll",
        DEFAULT_IFACE_PRE_ROLL,
        "--iface-post-roll",
        DEFAULT_IFACE_POST_ROLL,
        "--audacity-command-spacing",
        DEFAULT_AUDACITY_COMMAND_SPACING,
        "--audacity-reset-passes",
        DEFAULT_AUDACITY_RESET_PASSES,
        "--audacity-pre-import-delay",
        DEFAULT_AUDACITY_PRE_IMPORT_DELAY,
        "--audacity-post-import-delay",
        DEFAULT_AUDACITY_POST_IMPORT_DELAY,
        "--audacity-pre-save-delay",
        str(float(audacity_pre_save_delay)),
        "--audacity-post-save-delay",
        str(float(audacity_post_save_delay)),
    ]

    if teensy:
        cmd.append("--teensy-enable")
    else:
        cmd.append("--teensy-disable")

    if interface:
        cmd.append("--iface-enable")
        if teensy:
            cmd.append("--iface-trim-to-teensy")
            cmd.append("--iface-auto-align")
        else:
            cmd.append("--iface-no-trim-to-teensy")
            cmd.append("--iface-no-auto-align")
    else:
        cmd.append("--iface-disable")

    if audacity:
        cmd.append("--audacity-import")
    else:
        cmd.append("--no-audacity-import")

    if rigol:
        cmd.append("--post-rigol")

    if debug:
        cmd.append("--debug")

    return cmd


def build_rigol_command(experiment: str, trial: int) -> list[str]:
    return [
        sys.executable,
        "-m",
        RIGOL_MODULE,
        "--experiment",
        experiment,
        "--trial",
        str(trial),
    ]


def _normalize_device_arg(device_arg: str | None):
    if device_arg is None:
        return None
    text = str(device_arg).strip()
    if text.isdigit():
        return int(text)
    return text


def preflight_teensy(port: str) -> str:
    try:
        import serial
    except Exception as exc:
        raise RuntimeError("pyserial is not installed; install it before running Teensy capture") from exc

    try:
        with serial.Serial(port, 2000000, timeout=1, dsrdtr=False, rtscts=False, xonxoff=False) as ser:
            if not ser.is_open:
                raise RuntimeError(f"serial port {port} did not open")
    except Exception as exc:
        raise RuntimeError(f"Teensy serial port {port} is not available: {exc}") from exc

    return f"serial port {port} opened"


def preflight_audio_interface(device: str | None, channels: int, sample_rate: int) -> str:
    try:
        import sounddevice as sd
    except Exception as exc:
        raise RuntimeError("sounddevice is not installed; install it before running interface capture") from exc

    resolved_device = _normalize_device_arg(device)
    try:
        info = sd.query_devices(resolved_device, kind="input")
        max_inputs = int(info.get("max_input_channels", 0))
        if max_inputs < channels:
            raise RuntimeError(
                f"device {resolved_device} has only {max_inputs} input channels; requested {channels}"
            )
        with sd.InputStream(
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
            device=resolved_device,
            blocksize=0,
        ):
            pass
    except Exception as exc:
        raise RuntimeError(f"audio interface input device {resolved_device} is not available: {exc}") from exc

    name = str(info.get("name", resolved_device))
    return f"{name} ({channels} ch @ {sample_rate} Hz) opened"


def preflight_rigol() -> str:
    try:
        from ds1054z import DS1054Z
        from rigol.common import SCOPE_IP
    except Exception as exc:
        raise RuntimeError("Rigol dependencies are not installed; install ds1054z/python-vxi11 before scope capture") from exc

    try:
        with socket.create_connection((SCOPE_IP, 80), timeout=3.0):
            pass
    except (socket.timeout, ConnectionRefusedError, OSError) as exc:
        raise RuntimeError(f"scope is not reachable at {SCOPE_IP}: {exc}") from exc

    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            scope = ex.submit(DS1054Z, SCOPE_IP).result(timeout=8.0)
    except FuturesTimeout as exc:
        raise RuntimeError(f"VXI-11 connection to {SCOPE_IP} timed out") from exc
    except Exception as exc:
        raise RuntimeError(f"could not connect to scope at {SCOPE_IP}: {exc}") from exc

    return f"DS1054Z at {SCOPE_IP} responded as {scope.idn}"


def run_preflight_checks(teensy: bool, interface: bool, rigol: bool) -> None:
    checks: list[tuple[str, callable]] = []
    if teensy:
        checks.append(("Teensy", lambda: preflight_teensy(DEFAULT_PORT)))
    if interface:
        checks.append(
            (
                "Audio interface",
                lambda: preflight_audio_interface(
                    DEFAULT_IFACE_DEVICE,
                    int(DEFAULT_IFACE_CHANNELS),
                    int(DEFAULT_IFACE_SAMPLE_RATE),
                ),
            )
        )
    if rigol:
        checks.append(("Rigol", preflight_rigol))

    if not checks:
        return

    print("\nPreflight connection checks:")
    failures: list[str] = []
    for label, check in checks:
        print(f"  {label}: checking...", end="", flush=True)
        try:
            detail = check()
        except Exception as exc:
            print(" failed")
            failures.append(f"{label}: {exc}")
        else:
            print(f" ok ({detail})")

    if failures:
        print("\nRequired connection check failed before trial metadata entry:")
        for failure in failures:
            print(f"  - {failure}")
        print("\nConnect the required device(s), or rerun with --skip-preflight if you need to bypass this check.")
        raise SystemExit(1)

    print("All required connections are available.\n")


def main() -> int:
    args = parse_args()

    if args.skip_preflight and args.preflight_only:
        raise SystemExit("--skip-preflight cannot be combined with --preflight-only")

    if not CAPTURE_SCRIPT.exists():
        print(f"Capture script not found: {CAPTURE_SCRIPT}")
        return 1
    if not RIGOL_SCRIPT.exists():
        print(f"Rigol script not found: {RIGOL_SCRIPT}")
        return 1

    if args.experiment and args.experiment.strip():
        experiment = args.experiment.strip()
    else:
        experiment = prompt_text("Experiment", default=suggest_last_experiment(OUTPUT_DIR))

    state_path = state_path_for(experiment)
    state = load_state(state_path)
    suggested_trial, suggested_duration, state_trials = suggest_trial_and_duration(state)

    exp_dir = build_experiment_paths(OUTPUT_DIR, experiment)["exp_dir"]
    existing_trials = state_trials | set(existing_trial_numbers(exp_dir))
    if existing_trials:
        suggested_trial = max(int(suggested_trial), max(existing_trials) + 1)

    print("LTDM trial runner")
    print(f"Experiment: {experiment}")
    print(f"State file: {state_path}")

    profile = resolve_profile(args)
    profile_config = PROFILE_SETTINGS[profile]
    teensy = bool(profile_config["teensy"])
    interface = bool(profile_config["interface"])
    audacity = bool(profile_config["audacity"])
    rigol = bool(profile_config["rigol"])

    if args.trial is not None:
        if int(args.trial) < 1:
            raise SystemExit("--trial must be >= 1")
        trial = int(args.trial)
    else:
        trial = prompt_int("Trial number", int(suggested_trial), min_value=1)

    duration_s = None
    if args.duration is not None:
        if int(args.duration) < 1:
            raise SystemExit("--duration must be >= 1")
        duration_s = int(args.duration)
    else:
        duration_default = suggest_duration_for_trial(experiment, trial, suggested_duration)
        if profile != "rigol_only":
            duration_s = prompt_int("Trial duration (seconds)", duration_default, min_value=1)

    prompt_profile_field_changes(OUTPUT_DIR, experiment)

    if not args.skip_preflight:
        run_preflight_checks(teensy, interface, rigol)
    if args.preflight_only:
        return 0

    if trial in existing_trials:
        print(f"Trial {trial} already exists. Continuing will rerun/replace that trial in timeline state.")

    print("\nResolved profile settings:")
    print(f"  profile: {profile}")
    print(f"  teensy: {teensy}")
    print(f"  interface: {interface}")
    print(f"  audacity: {audacity}")
    print(f"  rigol: {rigol}")
    if profile != "rigol_only":
        print(f"  duration_s: {int(duration_s)}")
    print(f"  debug: {bool(args.debug)}")

    if profile == "rigol_only":
        cmd = build_rigol_command(experiment, trial)
    else:
        cmd = build_capture_command(
            experiment,
            trial,
            int(duration_s),
            teensy,
            interface,
            audacity,
            rigol,
            bool(args.debug),
            float(args.audacity_pre_save_delay),
            float(args.audacity_post_save_delay),
        )

    print("\nRunning:")
    print(" ".join(cmd))
    print("")

    completed = subprocess.run(cmd, cwd=str(BASE_DIR))
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
