from __future__ import annotations

import json
import math
from pathlib import Path

from core.path_layout import build_experiment_paths

TRIAL_INDEX_NAME = "trials_diff.json"


def trial_index_path(output_dir: str | Path, experiment: str) -> Path:
    return build_experiment_paths(output_dir, experiment)["orchestration_dir"] / TRIAL_INDEX_NAME


def load_trial_index(output_dir: str | Path, experiment: str) -> dict:
    path = trial_index_path(output_dir, experiment)
    data: dict = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    data.setdefault("experiment_title", experiment)
    if not isinstance(data.get("trials"), list):
        data["trials"] = []
    return data


def save_trial_index(output_dir: str | Path, experiment: str, data: dict) -> Path:
    path = trial_index_path(output_dir, experiment)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def prompt_trial_fields(defaults: dict[str, str] | None = None) -> dict[str, str]:
    import questionary

    base = dict(defaults or {})
    fields: dict[str, str] = {}

    fields["trial_description"] = questionary.text(
        "Trial description:",
        default=base.get("trial_description", ""),
    ).ask() or base.get("trial_description", "")

    return {k: str(v).strip() for k, v in fields.items()}


def ensure_trial_fields(output_dir: str | Path, experiment: str, trial_number: int) -> dict[str, str]:
    """Prompt for the description of this trial.

    Pre-fills defaults from this same trial's own prior metadata when overwriting/rerunning a
    trial so the previous description can just be confirmed. A new trial starts with a blank
    description.
    """
    from core.trial_metadata import get_reference_trial_metadata

    reference = get_reference_trial_metadata(output_dir, experiment, trial_number)
    if reference is None:
        return prompt_trial_fields()

    is_own_trial = int(reference.get("trial_number", -1)) == int(trial_number)
    defaults = {}
    if is_own_trial:
        defaults["trial_description"] = str(reference.get("trial_description", ""))
    return prompt_trial_fields(defaults=defaults)


def _flatten_metadata(value: object, prefix: str = "") -> dict[str, object]:
    """Convert nested metadata into stable, scalar diff columns."""
    if isinstance(value, dict):
        flattened: dict[str, object] = {}
        for key, child in value.items():
            child_prefix = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(_flatten_metadata(child, child_prefix))
        return flattened
    if isinstance(value, list):
        flattened = {}
        for index, child in enumerate(value):
            # Rows with a "label" (e.g. timing_table entries) are keyed by that label instead of
            # their index, so diff columns read as e.g. "tdm_timing.timing_table.main_sense_pulse_end.cycle_value".
            if isinstance(child, dict) and isinstance(child.get("label"), str):
                child_key = child["label"]
                child = {k: v for k, v in child.items() if k != "label"}
            else:
                child_key = index
            flattened.update(_flatten_metadata(child, f"{prefix}.{child_key}"))
        return flattened
    return {prefix: value}


def _is_interpreted_control_field(key: str) -> bool:
    return key.startswith("controls.interpreted_state.")


def _is_numeric_interpreted_control(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _normalise_diff_value(key: str, value: object) -> object:
    if _is_interpreted_control_field(key) and _is_numeric_interpreted_control(value):
        return f"{math.trunc(float(value) * 100) / 100:.2f}"
    return value


def _fields_differ(key: str, values: list[object]) -> bool:
    if _is_interpreted_control_field(key):
        numeric_values = [float(value) for value in values if _is_numeric_interpreted_control(value)]
        if numeric_values and len(numeric_values) == len(values):
            return max(numeric_values) - min(numeric_values) > 0.01 + 1e-9
    return len({json.dumps(value, sort_keys=True, default=str) for value in values}) > 1


def rebuild_trial_index(output_dir: str | Path, experiment: str) -> Path:
    """Rebuild trials_diff.json from scratch by diffing every trial's trial_metadata.json.

    Nested metadata is flattened into columns. Only fields whose value differs across at least
    two trials are kept, so the index highlights what actually changed instead of duplicating
    everything already in each trial_metadata.json. Capture timestamps and generated file lists
    are excluded because they change as a consequence of every capture, not the trial settings.
    """
    from core.path_layout import existing_trial_numbers, find_trial_dir
    from core.trial_metadata import load_trial_metadata

    paths = build_experiment_paths(output_dir, experiment)
    exp_dir = paths["exp_dir"]

    records: list[dict] = []
    for trial_number in existing_trial_numbers(exp_dir):
        trial_dir = find_trial_dir(exp_dir, trial_number)
        if trial_dir is None:
            continue
        trial_metadata_path = trial_dir / "trial_metadata.json"
        data = load_trial_metadata(trial_metadata_path)
        if not data:
            continue

        diff_source = {
            key: value
            for key, value in data.items()
            if key not in {
                "capture_time_utc",
                "capture_time_local",
                "files",
                "operator",
            }
        }
        streams = diff_source.get("streams")
        if isinstance(streams, dict):
            interface = streams.get("interface")
            if isinstance(interface, dict):
                alignment = interface.get("alignment")
                if isinstance(alignment, dict):
                    interface["alignment"] = {
                        key: value
                        for key, value in alignment.items()
                        if key not in {
                            "lag_iface_samples",
                            "lag_ms",
                            "lag_teensy_samples",
                            "score",
                        }
                    }
                interface.pop("channel_peak", None)
                interface.pop("channel_rms", None)
        controls = diff_source.get("controls")
        interpreted_controls = (
            controls.get("interpreted_state", {}) if isinstance(controls, dict) else {}
        )
        if not isinstance(interpreted_controls, dict):
            interpreted_controls = {}
        diff_source["controls"] = {"interpreted_state": interpreted_controls}
        firmware = diff_source.get("firmware")
        if isinstance(firmware, dict):
            # report_raw duplicates the normalised tdm_timing/controls blocks; keep it in
            # trial_metadata.json as a raw audit trail but drop it from the diff table.
            firmware.pop("report_raw", None)
        timing = diff_source.get("timing")
        if isinstance(timing, dict):
            diff_source["timing"] = {
                key: value for key, value in timing.items() if key not in {"monotonic", "derived"}
            }
        audacity = diff_source.get("audacity")
        if isinstance(audacity, dict):
            diff_source["audacity"] = {
                key: value for key, value in audacity.items() if key != "lifecycle_events"
            }

        records.append(
            {
                "trial_number": trial_number,
                "fields": _flatten_metadata(diff_source),
            }
        )

    all_keys: set[str] = set()
    for record in records:
        all_keys.update(record["fields"].keys())

    varying_keys = sorted(
        key for key in all_keys
        if _fields_differ(key, [record["fields"].get(key, "") for record in records])
    )

    trials_out = []
    for record in records:
        row = {"trial_number": record["trial_number"]}
        for key in varying_keys:
            row[key] = _normalise_diff_value(key, record["fields"].get(key, ""))
        trials_out.append(row)

    return save_trial_index(output_dir, experiment, {"experiment_title": experiment, "trials": trials_out})
