from __future__ import annotations

from datetime import datetime
import getpass
import json
from pathlib import Path

from core.path_layout import build_experiment_paths


EXPERIMENT_PROFILE_NAME = "experiment_profile.json"

# Fields that live on experiment_profile.json but are experiment-scoped bookkeeping, not
# user-reported trial variables, so they are never embedded into a trial's metadata snapshot.
PROFILE_ONLY_KEYS = {"experiment_title", "experiment_description", "operator", "updated_at"}

# Literal value written into experiment_profile.json for a field once it's been observed to
# change between trials. It is not a usable value itself; each trial prompts for the real value.
VARIABLE_MARKER = "VARIABLE"

PROFILE_FIELD_ORDER = (
    "string_material",
    "string_resistance_ohm",
    "string_fundamental_hz",
    "string_gauge_mm",
    "speaking_length_cm",
    "magnet_position_cm",
    "magnet_distance_mm",
    "magnet_geometry",
    "magnet_grade",
    "magnet_pull_strength_kg",
    "magnets_in_stack",
)


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
    payload["updated_at"] = datetime.now().isoformat()
    profile_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return profile_path


def profile_snapshot_fields(profile: dict[str, str]) -> dict[str, str]:
    """User-reported profile fields eligible for embedding into a trial's metadata snapshot."""
    return {k: v for k, v in profile.items() if k not in PROFILE_ONLY_KEYS}


def resolve_trial_profile_snapshot(
    profile: dict[str, str],
    previous_snapshot: dict[str, str] | None,
) -> tuple[dict[str, str], dict[str, str], bool]:
    """Resolve this trial's experiment-profile snapshot.

    Fields already marked VARIABLE_MARKER are prompted for (defaulting to the previous trial's
    value). Fields with a literal value that differs from the previous trial's recorded value are
    used as-is for this trial, and flagged VARIABLE_MARKER in the profile going forward.

    Returns (snapshot, possibly-updated profile, whether the profile changed).
    """
    import questionary

    previous_snapshot = previous_snapshot or {}
    candidate_fields = profile_snapshot_fields(profile)
    snapshot: dict[str, str] = {}
    updated_profile = dict(profile)
    profile_changed = False

    for key, raw_value in candidate_fields.items():
        value = str(raw_value)
        prev_value = previous_snapshot.get(key)
        if value == VARIABLE_MARKER:
            default = str(prev_value) if prev_value is not None else ""
            answer = questionary.text(
                f"{key} (varies between trials) for this trial:",
                default=default,
            ).ask()
            snapshot[key] = str(answer).strip() if answer is not None else default
        else:
            snapshot[key] = value
            if prev_value is not None and str(prev_value) != value:
                updated_profile[key] = VARIABLE_MARKER
                profile_changed = True

    return snapshot, updated_profile, profile_changed


def prompt_profile_field_changes(output_dir: str | Path, experiment: str) -> dict[str, str]:
    """Optionally let the user change any user-reported profile field before this trial runs.

    Loads the current experiment_profile.json, offers to edit any of its user-reported fields via
    questionary, and saves the result if anything changed. A field changed here will be detected
    as a difference from the previous trial (and flagged VARIABLE_MARKER) the next time
    `resolve_trial_profile_snapshot` runs for this experiment.
    """
    import questionary

    profile = load_experiment_profile(output_dir, experiment)
    editable_fields = profile_snapshot_fields(profile)
    editable_keys = [key for key in PROFILE_FIELD_ORDER if key in editable_fields]
    editable_keys.extend(sorted(set(editable_fields) - set(editable_keys)))
    if not editable_keys:
        return profile

    updated = dict(profile)
    value_column = max(len(key) for key in editable_keys) + 3
    while True:
        choices = [questionary.Choice("done", value="__done__")]
        for key in editable_keys:
            current = str(updated.get(key, "")).strip() or "(empty)"
            label = f"{key + ':':<{value_column}}{current}"
            choices.append(questionary.Choice(label, value=key))

        selected = questionary.select("Change which parameter?", choices=choices).ask()
        if selected in (None, "__done__"):
            break

        new_value = questionary.text(f"{selected}:", default=str(updated.get(selected, ""))).ask()
        if new_value is not None:
            updated[selected] = str(new_value).strip()

    if updated == profile:
        return profile

    save_experiment_profile(output_dir, experiment, updated)
    print("Updated experiment profile with new trial values.")
    return updated


def prompt_experiment_profile(experiment: str, defaults: dict[str, str] | None = None) -> dict[str, str]:
    import questionary

    base = dict(defaults or {})
    meta: dict[str, str] = {}

    meta["experiment_description"] = questionary.text(
        "Experiment description:",
        default=base.get("experiment_description", ""),
    ).ask() or base.get("experiment_description", "")

    meta["operator"] = questionary.text(
        "Operator name:",
        default=base.get("operator", getpass.getuser()),
    ).ask() or base.get("operator", getpass.getuser())

    meta["string_material"] = questionary.text(
        "String material:",
        default=base.get("string_material", ""),
    ).ask() or base.get("string_material", "")

    meta["string_resistance_ohm"] = questionary.text(
        "String resistance (ohm):",
        default=base.get("string_resistance_ohm", ""),
    ).ask() or base.get("string_resistance_ohm", "")

    meta["string_fundamental_hz"] = questionary.text(
        "String fundamental frequency (Hz):",
        default=base.get("string_fundamental_hz", ""),
    ).ask() or base.get("string_fundamental_hz", "")

    meta["string_gauge_mm"] = questionary.text(
        "String gauge (mm):",
        default=base.get("string_gauge_mm", ""),
    ).ask() or base.get("string_gauge_mm", "")

    meta["speaking_length_cm"] = questionary.text(
        "Speaking length of string (cm):",
        default=base.get("speaking_length_cm", ""),
    ).ask() or base.get("speaking_length_cm", "")

    meta["magnet_position_cm"] = questionary.text(
        "Magnet position along string (cm):",
        default=base.get("magnet_position_cm", ""),
    ).ask() or base.get("magnet_position_cm", "")

    meta["magnet_distance_mm"] = questionary.text(
        "Magnet distance from string center (mm):",
        default=base.get("magnet_distance_mm", ""),
    ).ask() or base.get("magnet_distance_mm", "")

    meta["magnet_geometry"] = questionary.text(
        "Magnet geometry (e.g. 20 x 10 x 5 mm, or shape description):",
        default=base.get("magnet_geometry", ""),
    ).ask() or base.get("magnet_geometry", "")

    meta["magnet_grade"] = questionary.text(
        "Magnet grade (e.g. N35):",
        default=base.get("magnet_grade", ""),
    ).ask() or base.get("magnet_grade", "")

    meta["magnet_pull_strength_kg"] = questionary.text(
        "Magnet pull strength (kg):",
        default=base.get("magnet_pull_strength_kg", ""),
    ).ask() or base.get("magnet_pull_strength_kg", "")

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
