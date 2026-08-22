from __future__ import annotations

from datetime import datetime
import getpass
import json
from pathlib import Path

from path_layout import build_experiment_paths


EXPERIMENT_PROFILE_NAME = "experiment_profile.json"
PROFILE_FORMAT_VERSION = 1


def experiment_profile_path(output_dir: str | Path, experiment: str) -> Path:
    return build_experiment_paths(output_dir, experiment)["orchestration_dir"] / EXPERIMENT_PROFILE_NAME


def load_experiment_profile(output_dir: str | Path, experiment: str) -> dict[str, str]:
    profile_path = experiment_profile_path(output_dir, experiment)
    if not profile_path.exists():
        return {}
    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def save_experiment_profile(output_dir: str | Path, experiment: str, profile: dict[str, str]) -> Path:
    profile_path = experiment_profile_path(output_dir, experiment)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {k: str(v).strip() for k, v in profile.items()}
    payload["experiment_title"] = experiment
    payload["profile_format_version"] = str(PROFILE_FORMAT_VERSION)
    payload["updated_at"] = datetime.now().isoformat()
    profile_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return profile_path


def prompt_experiment_profile(experiment: str, defaults: dict[str, str] | None = None) -> dict[str, str]:
    import questionary

    base = dict(defaults or {})
    meta: dict[str, str] = {}

    meta["operator"] = questionary.text(
        "Operator name:",
        default=base.get("operator", getpass.getuser()),
    ).ask() or base.get("operator", getpass.getuser())

    meta["description"] = questionary.text(
        "Short description / notes:",
        default=base.get("description", ""),
    ).ask() or base.get("description", "")

    meta["string_material"] = questionary.text(
        "String material:",
        default=base.get("string_material", ""),
    ).ask() or base.get("string_material", "")

    meta["speaking_length_cm"] = questionary.text(
        "Speaking length of string (cm):",
        default=base.get("speaking_length_cm", ""),
    ).ask() or base.get("speaking_length_cm", "")

    meta["string_gauge_mm"] = questionary.text(
        "String gauge (mm):",
        default=base.get("string_gauge_mm", ""),
    ).ask() or base.get("string_gauge_mm", "")

    meta["string_resistance_ohm"] = questionary.text(
        "String resistance (ohm):",
        default=base.get("string_resistance_ohm", ""),
    ).ask() or base.get("string_resistance_ohm", "")

    meta["string_fundamental_hz"] = questionary.text(
        "String fundamental frequency (Hz):",
        default=base.get("string_fundamental_hz", ""),
    ).ask() or base.get("string_fundamental_hz", "")

    meta["magnet_grade"] = questionary.text(
        "Magnet grade (e.g. N35):",
        default=base.get("magnet_grade", ""),
    ).ask() or base.get("magnet_grade", "")

    meta["magnet_pull_strength_kg"] = questionary.text(
        "Magnet pull strength (kg):",
        default=base.get("magnet_pull_strength_kg", ""),
    ).ask() or base.get("magnet_pull_strength_kg", "")

    meta["magnet_position_cm"] = questionary.text(
        "Magnet position along string (cm):",
        default=base.get("magnet_position_cm", ""),
    ).ask() or base.get("magnet_position_cm", "")

    meta["magnet_distance_mm"] = questionary.text(
        "Magnet distance from string center (mm):",
        default=base.get("magnet_distance_mm", ""),
    ).ask() or base.get("magnet_distance_mm", "")

    meta["magnet_dimensions_mm"] = questionary.text(
        "Magnet dimensions (mm x mm x mm):",
        default=base.get("magnet_dimensions_mm", ""),
    ).ask() or base.get("magnet_dimensions_mm", "")

    meta["magnets_in_stack"] = questionary.text(
        "Number of magnets in stack:",
        default=base.get("magnets_in_stack", ""),
    ).ask() or base.get("magnets_in_stack", "")

    return {k: str(v).strip() for k, v in meta.items()}


def ensure_experiment_profile(output_dir: str | Path, experiment: str) -> tuple[dict[str, str], Path, bool]:
    profile = load_experiment_profile(output_dir, experiment)
    profile_path = experiment_profile_path(output_dir, experiment)
    if profile:
        return profile, profile_path, False

    print(f"No experiment profile found for '{experiment}'. Creating one now.")
    profile = prompt_experiment_profile(experiment, defaults={"experiment_title": experiment})
    profile_path = save_experiment_profile(output_dir, experiment, profile)
    return profile, profile_path, True


def prompt_scope_channel_labels(defaults: dict[str, str] | None = None) -> dict[str, str]:
    import questionary

    base = dict(defaults or {})
    labels: dict[str, str] = {}
    for ch in ("CHAN1", "CHAN2", "CHAN3", "CHAN4"):
        key = f"channel_label_{ch}"
        labels[key] = questionary.text(
            f"Channel {ch} label:",
            default=base.get(key, ch),
        ).ask() or base.get(key, ch)
    return {k: str(v).strip() for k, v in labels.items()}


def ensure_scope_channel_labels(
    output_dir: str | Path,
    experiment: str,
    profile: dict[str, str],
    *,
    prompt_when_missing: bool = True,
) -> tuple[dict[str, str], Path, bool]:
    updated = dict(profile)
    missing = [f"channel_label_{ch}" for ch in ("CHAN1", "CHAN2", "CHAN3", "CHAN4") if not str(updated.get(f"channel_label_{ch}", "")).strip()]
    if missing and prompt_when_missing:
        updated.update(prompt_scope_channel_labels(updated))
        profile_path = save_experiment_profile(output_dir, experiment, updated)
        return updated, profile_path, True

    for ch in ("CHAN1", "CHAN2", "CHAN3", "CHAN4"):
        key = f"channel_label_{ch}"
        updated[key] = str(updated.get(key, ch)).strip() or ch
    profile_path = experiment_profile_path(output_dir, experiment)
    return updated, profile_path, False
