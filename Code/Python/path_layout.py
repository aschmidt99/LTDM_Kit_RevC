from __future__ import annotations

import re
from pathlib import Path


TRIAL_DIR_PREFIX = "trial_"
TRIAL_RE = re.compile(r"^trial_(\d+)$")
CAPTURE_RE = re.compile(r"^capture_(\d+)$")


def safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in value).strip().replace(" ", "_") or "untitled"


def build_experiment_paths(output_dir: str | Path, experiment: str) -> dict[str, Path]:
    base_dir = Path(output_dir)
    exp_dir = base_dir / safe_name(experiment)
    orchestration_dir = exp_dir / "orchestration"
    return {
        "base_dir": base_dir,
        "exp_dir": exp_dir,
        "orchestration_dir": orchestration_dir,
    }

def existing_trial_numbers(exp_dir: Path) -> list[int]:
    trials_dir = exp_dir / "trials"
    if not trials_dir.exists():
        return []
    trials: set[int] = set()
    for trial_dir in trials_dir.glob("trial_*"):
        if not trial_dir.is_dir():
            continue
        m = TRIAL_RE.match(trial_dir.name)
        if not m:
            continue
        trials.add(int(m.group(1)))
    return sorted(trials)


def find_trial_dir(exp_dir: Path, trial: int) -> Path | None:
    trials_dir = exp_dir / "trials"
    if not trials_dir.exists():
        return None
    needle = f"{TRIAL_DIR_PREFIX}{int(trial):04d}"
    matches = [p for p in trials_dir.glob(needle) if p.is_dir()]
    if not matches:
        return None
    matches.sort(key=lambda p: p.name)
    return matches[-1]


def build_trial_paths(output_dir: str | Path, experiment: str, trial: int, create: bool = True) -> dict[str, Path]:
    paths = build_experiment_paths(output_dir, experiment)
    exp_dir = paths["exp_dir"]
    orchestration_dir = paths["orchestration_dir"]

    existing = find_trial_dir(exp_dir, trial)
    if existing is not None:
        trial_dir = existing
    else:
        trial_dir = exp_dir / "trials" / f"{TRIAL_DIR_PREFIX}{int(trial):04d}"

    macro_audio_dir = trial_dir / "macro_audio"
    audacity_dir = macro_audio_dir / "audacity"
    micro_scope_dir = trial_dir / "micro_scope"
    sync_dir = trial_dir / "sync"
    qc_dir = trial_dir / "qc"
    trial_manifest_path = trial_dir / "trial_manifest.json"

    if create:
        exp_dir.mkdir(parents=True, exist_ok=True)
        orchestration_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / "analysis").mkdir(parents=True, exist_ok=True)
        (exp_dir / "processed").mkdir(parents=True, exist_ok=True)
        (exp_dir / "reports").mkdir(parents=True, exist_ok=True)
        (exp_dir / "trials").mkdir(parents=True, exist_ok=True)
        trial_dir.mkdir(parents=True, exist_ok=True)

    return {
        **paths,
        "trial_dir": trial_dir,
        "macro_audio_dir": macro_audio_dir,
        "audacity_dir": audacity_dir,
        "micro_scope_dir": micro_scope_dir,
        "sync_dir": sync_dir,
        "qc_dir": qc_dir,
        "trial_manifest_path": trial_manifest_path,
    }


def next_capture_dir(micro_scope_dir: Path) -> Path:
    max_idx = 0
    if micro_scope_dir.exists():
        for child in micro_scope_dir.iterdir():
            if not child.is_dir():
                continue
            m = CAPTURE_RE.match(child.name)
            if not m:
                continue
            max_idx = max(max_idx, int(m.group(1)))
    return micro_scope_dir / f"capture_{max_idx + 1:03d}"
