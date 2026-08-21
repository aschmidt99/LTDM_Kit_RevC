from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


TRIAL_DIR_PREFIX = "trial_"
SESSION_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_session(\d+)$")
TRIAL_RE = re.compile(r"^trial_(\d+)$")
CAPTURE_RE = re.compile(r"^capture_(\d+)$")


def safe_name(value: str) -> str:
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in value).strip().replace(" ", "_") or "untitled"


def build_experiment_paths(output_dir: str | Path, experiment: str) -> dict[str, Path]:
    base_dir = Path(output_dir)
    exp_dir = base_dir / safe_name(experiment)
    orchestration_dir = exp_dir / "orchestration"
    sessions_dir = exp_dir / "sessions"
    return {
        "base_dir": base_dir,
        "exp_dir": exp_dir,
        "orchestration_dir": orchestration_dir,
        "sessions_dir": sessions_dir,
    }


def _today_session_name(sessions_dir: Path) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    max_idx = 0
    if sessions_dir.exists():
        for child in sessions_dir.iterdir():
            if not child.is_dir():
                continue
            m = SESSION_RE.match(child.name)
            if not m:
                continue
            if m.group(1) != today:
                continue
            max_idx = max(max_idx, int(m.group(2)))
    idx = max(1, max_idx)
    return f"{today}_session{idx:02d}"


def latest_session_dir(exp_dir: Path) -> Path | None:
    sessions_dir = exp_dir / "sessions"
    if not sessions_dir.exists():
        return None
    candidates: list[tuple[datetime, int, Path]] = []
    for child in sessions_dir.iterdir():
        if not child.is_dir():
            continue
        m = SESSION_RE.match(child.name)
        if not m:
            continue
        dt = datetime.strptime(m.group(1), "%Y-%m-%d")
        idx = int(m.group(2))
        candidates.append((dt, idx, child))
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[-1][2]


def existing_trial_numbers(exp_dir: Path) -> list[int]:
    sessions_dir = exp_dir / "sessions"
    if not sessions_dir.exists():
        return []
    trials: set[int] = set()
    for trial_dir in sessions_dir.glob("*/trials/trial_*"):
        if not trial_dir.is_dir():
            continue
        m = TRIAL_RE.match(trial_dir.name)
        if not m:
            continue
        trials.add(int(m.group(1)))
    return sorted(trials)


def find_trial_dir(exp_dir: Path, trial: int) -> Path | None:
    sessions_dir = exp_dir / "sessions"
    if not sessions_dir.exists():
        return None
    needle = f"{TRIAL_DIR_PREFIX}{int(trial):04d}"
    matches = [p for p in sessions_dir.glob(f"*/trials/{needle}") if p.is_dir()]
    if not matches:
        return None
    matches.sort(key=lambda p: p.parent.parent.name)
    return matches[-1]


def ensure_session_dir(exp_dir: Path) -> Path:
    sessions_dir = exp_dir / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    session_name = _today_session_name(sessions_dir)
    session_dir = sessions_dir / session_name
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "logs").mkdir(parents=True, exist_ok=True)
    (session_dir / "trials").mkdir(parents=True, exist_ok=True)
    return session_dir


def build_trial_paths(output_dir: str | Path, experiment: str, trial: int, create: bool = True) -> dict[str, Path]:
    paths = build_experiment_paths(output_dir, experiment)
    exp_dir = paths["exp_dir"]
    orchestration_dir = paths["orchestration_dir"]

    existing = find_trial_dir(exp_dir, trial)
    if existing is not None:
        trial_dir = existing
        session_dir = trial_dir.parent.parent
    else:
        session_dir = ensure_session_dir(exp_dir)
        trial_dir = session_dir / "trials" / f"{TRIAL_DIR_PREFIX}{int(trial):04d}"

    macro_audio_dir = trial_dir / "macro_audio"
    teensy_dir = macro_audio_dir / "teensy"
    interface_dir = macro_audio_dir / "interface"
    audacity_dir = macro_audio_dir / "audacity"
    micro_scope_dir = trial_dir / "micro_scope"
    sync_dir = trial_dir / "sync"
    qc_dir = trial_dir / "qc"

    if create:
        exp_dir.mkdir(parents=True, exist_ok=True)
        orchestration_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / "analysis").mkdir(parents=True, exist_ok=True)
        (exp_dir / "processed").mkdir(parents=True, exist_ok=True)
        (exp_dir / "reports").mkdir(parents=True, exist_ok=True)
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "logs").mkdir(parents=True, exist_ok=True)
        (session_dir / "trials").mkdir(parents=True, exist_ok=True)
        trial_dir.mkdir(parents=True, exist_ok=True)
        macro_audio_dir.mkdir(parents=True, exist_ok=True)
        teensy_dir.mkdir(parents=True, exist_ok=True)
        interface_dir.mkdir(parents=True, exist_ok=True)
        audacity_dir.mkdir(parents=True, exist_ok=True)
        micro_scope_dir.mkdir(parents=True, exist_ok=True)
        sync_dir.mkdir(parents=True, exist_ok=True)
        qc_dir.mkdir(parents=True, exist_ok=True)

    return {
        **paths,
        "session_dir": session_dir,
        "trial_dir": trial_dir,
        "macro_audio_dir": macro_audio_dir,
        "teensy_dir": teensy_dir,
        "interface_dir": interface_dir,
        "audacity_dir": audacity_dir,
        "micro_scope_dir": micro_scope_dir,
        "sync_dir": sync_dir,
        "qc_dir": qc_dir,
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
