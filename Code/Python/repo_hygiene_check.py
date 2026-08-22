#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def git_ls_files(repo_root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=str(repo_root),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "git ls-files failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def is_generated_capture_path(path: Path) -> bool:
    parts = path.parts
    if ".DS_Store" in parts:
        return True
    if "__pycache__" in parts:
        return True
    if path.suffix == ".pyc":
        return True
    if len(parts) >= 6 and parts[:3] == ("Code", "Python", "experiments"):
        trial_segment = parts[5]
        if trial_segment.startswith("trial_"):
            return True
    if len(parts) >= 6 and parts[:3] == ("Code", "Python", "experiments"):
        if parts[5] == "audacity_timeline_state.json":
            return True
    if len(parts) >= 6 and parts[:3] == ("Code", "Python", "experiments"):
        if parts[5] == "orchestration":
            name = path.name
            if name.endswith(".aup3") or name.endswith(".aup3-shm") or name.endswith(".aup3-wal"):
                return True
    return False


def collect_warnings(repo_root: Path) -> dict[str, list[str]]:
    tracked = git_ls_files(repo_root)
    tracked_generated = [p for p in tracked if is_generated_capture_path(Path(p))]

    duplicates: list[str] = []
    if (repo_root / "Code" / "Python" / "PYTHON_README.md").exists() and (
        repo_root / "Code" / "Python" / "PYTHONS_README.md"
    ).exists():
        duplicates.append("Both Code/Python/PYTHON_README.md and Code/Python/PYTHONS_README.md exist")

    return {
        "tracked_generated_files": sorted(tracked_generated),
        "duplicate_readmes": duplicates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Check repository hygiene for generated capture artefacts.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    args = parser.parse_args()

    try:
        report = collect_warnings(REPO_ROOT)
    except RuntimeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    has_findings = any(report.values())

    if args.json:
        print(json.dumps(report, indent=2))
        return 1 if has_findings else 0

    print("Repository hygiene check")
    print(f"Repo root: {REPO_ROOT}")

    if report["tracked_generated_files"]:
        print("\nTracked generated files (should usually be removed from git index):")
        for path in report["tracked_generated_files"]:
            print(f"  - {path}")
        print("\nSuggested cleanup command:")
        print("  git rm --cached <path>")
    else:
        print("\nNo tracked generated capture files detected.")

    if report["duplicate_readmes"]:
        print("\nReadme naming issues:")
        for message in report["duplicate_readmes"]:
            print(f"  - {message}")
    else:
        print("\nNo duplicate Python readme files detected.")

    return 1 if has_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())