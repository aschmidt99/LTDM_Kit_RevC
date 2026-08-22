#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
from pathlib import Path

from core.experiment_profile import load_experiment_profile, save_experiment_profile
from core.path_layout import build_experiment_paths, existing_trial_numbers

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

RESERVED_PROFILE_KEYS = {
    "experiment_title",
    "profile_format_version",
    "updated_at",
}

PROFILE_FIELD_LABELS = {
    "duration_seconds": "Default trial duration (s)",
    "operator": "Operator name",
    "description": "Short description / notes",
    "string_material": "String material",
    "speaking_length_cm": "Speaking length of string (cm)",
    "string_gauge_mm": "String gauge (mm)",
    "string_resistance_ohm": "String resistance (ohm)",
    "string_fundamental_hz": "String fundamental frequency (Hz)",
    "magnet_grade": "Magnet grade",
    "magnet_pull_strength_kg": "Magnet pull strength (kg)",
    "magnet_position_cm": "Magnet position along string (cm)",
    "magnet_distance_mm": "Magnet distance from string centre (mm)",
    "magnet_dimensions_mm": "Magnet dimensions (mm x mm x mm)",
    "magnets_in_stack": "Number of magnets in stack",
    "channel_label_CHAN1": "Scope channel CHAN1 label",
    "channel_label_CHAN2": "Scope channel CHAN2 label",
    "channel_label_CHAN3": "Scope channel CHAN3 label",
    "channel_label_CHAN4": "Scope channel CHAN4 label",
}

PROFILE_FIELD_ORDER = [
    "duration_seconds",
    "operator",
    "description",
    "string_material",
    "speaking_length_cm",
    "string_gauge_mm",
    "string_resistance_ohm",
    "string_fundamental_hz",
    "magnet_grade",
    "magnet_pull_strength_kg",
    "magnet_position_cm",
    "magnet_distance_mm",
    "magnet_dimensions_mm",
    "magnets_in_stack",
    "channel_label_CHAN1",
    "channel_label_CHAN2",
    "channel_label_CHAN3",
    "channel_label_CHAN4",
]


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
        text = str(default).strip() if raw is None else str(raw).strip()
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


def _field_label(key: str) -> str:
    return PROFILE_FIELD_LABELS.get(key, key.replace("_", " "))


def maybe_prompt_profile_updates(output_dir: str, experiment: str, trial: int) -> None:
    if trial < 2:
        return

    profile = load_experiment_profile(output_dir, experiment)
    if not profile:
        return

    import questionary

    if not str(profile.get("duration_seconds", "")).strip():
        profile["duration_seconds"] = str(DEFAULT_DURATION_S)

    editable_keys = [k for k in PROFILE_FIELD_ORDER if k in profile and k not in RESERVED_PROFILE_KEYS]
    extras = sorted(k for k in profile.keys() if k not in RESERVED_PROFILE_KEYS and k not in editable_keys)
    editable_keys.extend(extras)
    if not editable_keys:
        return

    changed = False
    while True:
        formatted_rows = []
        for key in editable_keys:
            label = _field_label(key)
            current = str(profile.get(key, "")).strip() or "(empty)"
            formatted_rows.append((key, label, current))
        max_label_len = max((len(label) for _, label, _ in formatted_rows), default=0)

        choices = [questionary.Choice("no", value="__no__")]
        for key, label, current in formatted_rows:
            dots = "." * max(3, (max_label_len - len(label)) + 3)
            prefix = f"{label} {dots} "
            if key == "description" and current and current != "(empty)":
                wrapped = textwrap.wrap(current, width=72, break_long_words=False, break_on_hyphens=False)
                if wrapped:
                    first = prefix + wrapped[0]
                    indent = " " * (len(prefix) + 4)
                    rest = [indent + line for line in wrapped[1:]]
                    title = "\n".join([first, *rest])
                else:
                    title = prefix + current
            else:
                title = prefix + current
            choices.append(questionary.Choice(title, value=key))

        selected = questionary.select("Change user-reported variable?", choices=choices).ask()
        if selected in {None, "__no__"}:
            break

        old_value = str(profile.get(selected, ""))
        new_value = questionary.text(f"{_field_label(selected)}:", default=old_value).ask()
        if new_value is None:
            continue

        cleaned = str(new_value).strip()
        if selected == "duration_seconds":
            try:
                if int(cleaned) < 1:
                    print("Duration must be >= 1")
                    continue
            except ValueError:
                print("Duration must be an integer")
                continue

        profile[selected] = cleaned
        changed = True

    if changed:
        profile_path = save_experiment_profile(output_dir, experiment, profile)
        print(f"Updated experiment profile: {profile_path}")


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


def main() -> int:
    args = parse_args()

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

    print("LTDM trial runner")
    print(f"Experiment: {experiment}")
    print(f"State file: {state_path}")

    if args.trial is not None:
        if int(args.trial) < 1:
            raise SystemExit("--trial must be >= 1")
        trial = int(args.trial)
    else:
        trial = prompt_int("Trial number", int(suggested_trial), min_value=1)

    profile = resolve_profile(args)
    profile_config = PROFILE_SETTINGS[profile]
    teensy = bool(profile_config["teensy"])
    interface = bool(profile_config["interface"])
    audacity = bool(profile_config["audacity"])
    rigol = bool(profile_config["rigol"])

    duration_s = None
    if profile != "rigol_only":
        if args.duration is not None:
            if int(args.duration) < 1:
                raise SystemExit("--duration must be >= 1")
            duration_s = int(args.duration)
        else:
            profile_data = load_experiment_profile(OUTPUT_DIR, experiment)
            raw_duration = str(profile_data.get("duration_seconds", "")).strip() if profile_data else ""
            if raw_duration:
                try:
                    duration_s = int(raw_duration)
                except ValueError:
                    duration_s = DEFAULT_DURATION_S
            else:
                duration_s = DEFAULT_DURATION_S

    if trial in existing_trials:
        print(f"Trial {trial} already exists. Continuing will rerun/replace that trial in timeline state.")

    maybe_prompt_profile_updates(OUTPUT_DIR, experiment, trial)

    if profile != "rigol_only" and args.duration is None:
        profile_data = load_experiment_profile(OUTPUT_DIR, experiment)
        raw_duration = str(profile_data.get("duration_seconds", "")).strip() if profile_data else ""
        if raw_duration:
            try:
                duration_s = int(raw_duration)
            except ValueError:
                duration_s = DEFAULT_DURATION_S
        else:
            duration_s = DEFAULT_DURATION_S

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
