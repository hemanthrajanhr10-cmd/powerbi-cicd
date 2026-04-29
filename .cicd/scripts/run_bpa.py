"""
Run Tabular Editor 2 Best Practice Analyzer against each SemanticModel.
Outputs violations to bpa-results/<model>/output.txt and bpa-results/summary.json.
"""

import glob
import json
import os
import subprocess
import sys
from pathlib import Path


def find_model_dirs() -> list[Path]:
    paths_env = os.environ.get("MODEL_PATHS", "").strip()
    if paths_env:
        dirs = [p.strip() for p in paths_env.split(",") if p.strip()]
    else:
        dirs = glob.glob("*.SemanticModel")
    return [Path(d) for d in dirs if Path(d).is_dir()]


def resolve_model_path(model_dir: Path) -> Path | None:
    for candidate in [
        model_dir / "model.bim",
        model_dir / "definition" / "model.bim",
        model_dir / "database.json",
        model_dir / "definition",   # TMDL folder — TE2 accepts the directory
    ]:
        if candidate.exists():
            return candidate
    return None


def run_bpa(te2: str, model_path: str, rules_path: str) -> tuple[int, str]:
    cmd = [te2, model_path, "-A", rules_path, "-BPA", "-V"]
    print(f"  CMD: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    return result.returncode, result.stdout + result.stderr


def parse_violations(output: str) -> list[str]:
    """Extract violation lines from TE2 BPA output."""
    violations = []
    for line in output.splitlines():
        stripped = line.strip()
        # TE2 BPA lines look like: "[Warning] RULE_ID: Object name - description"
        if stripped.startswith(("[Warning]", "[Error]", "BPA")):
            violations.append(stripped)
        elif "violation" in stripped.lower() or "rule" in stripped.lower():
            violations.append(stripped)
    return violations


def main():
    te2_path = os.environ.get("TE2_PATH", ".te2/TabularEditor.exe")
    rules_path = ".cicd/bpa/rules.json"

    if not Path(te2_path).exists():
        print(f"Tabular Editor 2 not found at '{te2_path}'")
        sys.exit(1)

    if not Path(rules_path).exists():
        print(f"BPA rules file not found at '{rules_path}'")
        sys.exit(1)

    model_dirs = find_model_dirs()
    if not model_dirs:
        print("No .SemanticModel directories found.")
        sys.exit(0)

    Path("bpa-results").mkdir(exist_ok=True)
    summary: dict[str, list[str]] = {}
    failed = False

    for model_dir in model_dirs:
        print(f"\n{'='*60}\nRunning BPA on: {model_dir.name}\n{'='*60}")

        model_path = resolve_model_path(model_dir)
        if not model_path:
            print(f"  Could not resolve model path in {model_dir}")
            continue

        safe = model_dir.name.replace(" ", "_").replace(".", "_")
        out_dir = Path(f"bpa-results/{safe}")
        out_dir.mkdir(parents=True, exist_ok=True)

        rc, output = run_bpa(te2_path, str(model_path), rules_path)
        (out_dir / "output.txt").write_text(output, encoding="utf-8")

        violations = parse_violations(output)
        summary[str(model_dir)] = violations

        if violations:
            failed = True
            print(f"\n  {len(violations)} BPA violation(s):")
            for v in violations:
                print(f"    :: {v}")
        else:
            print("\n  BPA passed — no violations.")

    Path("bpa-results/summary.json").write_text(json.dumps(summary, indent=2))
    print("\nBPA summary written to bpa-results/summary.json")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
