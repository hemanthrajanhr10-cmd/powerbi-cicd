"""
Model checks:
  1. Calculation group tables start with 'CG'
  2. Field parameter tables start with 'FP'
  3. Measures start with '.'
  4. Measures are in a display folder (not root)
  5. Visible columns are in a display folder (not root)
  6. Tables, measures, and visible columns all have descriptions
"""

import glob
import json
import os
import re
import sys
from pathlib import Path


# ── loaders ────────────────────────────────────────────────────────────────────

def find_model_dirs() -> list[Path]:
    paths_env = os.environ.get("MODEL_PATHS", "").strip()
    if paths_env:
        dirs = [p.strip() for p in paths_env.split(",") if p.strip()]
    else:
        dirs = glob.glob("*.SemanticModel")
    return [Path(d) for d in dirs if Path(d).is_dir()]


def load_model(model_dir: Path) -> tuple[dict | None, str]:
    """Return (model_dict, format_label). model_dict has key 'tables'."""
    for candidate in [
        model_dir / "model.bim",
        model_dir / "definition" / "model.bim",
        model_dir / "database.json",
    ]:
        if candidate.exists():
            raw = json.loads(candidate.read_text(encoding="utf-8"))
            tables = raw.get("model", raw).get("tables", [])
            return {"tables": tables}, "bim"

    tmdl_dir = model_dir / "definition"
    if tmdl_dir.is_dir():
        return load_tmdl(tmdl_dir), "tmdl"

    return None, "unknown"


def load_tmdl(tmdl_dir: Path) -> dict:
    tables = []
    tables_dir = tmdl_dir / "tables"
    if tables_dir.is_dir():
        for f in tables_dir.glob("*.tmdl"):
            tables.append(_parse_tmdl_table(f.read_text(encoding="utf-8"), f.stem))
    return {"tables": tables}


def _parse_tmdl_table(content: str, stem: str) -> dict:
    table: dict = {
        "name": stem,
        "description": "",
        "isCalculationGroup": False,
        "measures": [],
        "columns": [],
    }
    current: dict | None = None
    kind: str | None = None

    for line in content.splitlines():
        s = line.strip()
        if s.startswith("table "):
            table["name"] = s.split(" ", 1)[1].strip().strip("'\"")
        elif s.startswith("calculationGroup"):
            table["isCalculationGroup"] = True
        elif s.startswith("measure "):
            name = re.split(r"\s*=", s.split(" ", 1)[1], 1)[0].strip().strip("'\"")
            current = {"name": name, "description": "", "displayFolder": ""}
            kind = "measure"
            table["measures"].append(current)
        elif s.startswith("column "):
            name = re.split(r"[:\s]", s.split(" ", 1)[1], 1)[0].strip().strip("'\"")
            current = {"name": name, "description": "", "displayFolder": "", "isHidden": False, "type": ""}
            kind = "column"
            table["columns"].append(current)
        elif current is not None:
            if s.startswith("description:"):
                current["description"] = s.split(":", 1)[1].strip().strip("'\"")
            elif s.startswith("folder:") or s.startswith("displayFolder:"):
                current["displayFolder"] = s.split(":", 1)[1].strip().strip("'\"")
            elif s.startswith("isHidden:") and kind == "column":
                current["isHidden"] = s.split(":", 1)[1].strip().lower() == "true"
            elif s.startswith("dataType:") and kind == "column":
                current["type"] = s.split(":", 1)[1].strip()
        if s.startswith("description:") and current is None:
            table["description"] = s.split(":", 1)[1].strip().strip("'\"")

    return table


# ── field-parameter heuristic ─────────────────────────────────────────────────

_FP_COL_HINTS = re.compile(r"Fields|Parameter|Ordinal", re.IGNORECASE)

def _is_field_param(table: dict) -> bool:
    col_names = [c.get("name", "") for c in table.get("columns", [])]
    return any(_FP_COL_HINTS.search(n) for n in col_names)


# ── checks ─────────────────────────────────────────────────────────────────────

def check_calc_groups(tables: list[dict]) -> list[str]:
    return [
        f"Calculation group table '{t['name']}' does not start with 'CG'"
        for t in tables
        if t.get("isCalculationGroup") and not t["name"].startswith("CG")
    ]


def check_field_params(tables: list[dict]) -> list[str]:
    return [
        f"Field parameter table '{t['name']}' does not start with 'FP'"
        for t in tables
        if _is_field_param(t) and not t["name"].startswith("FP")
    ]


def check_measure_prefix(tables: list[dict]) -> list[str]:
    issues = []
    for t in tables:
        if t.get("isCalculationGroup"):
            continue
        for m in t.get("measures", []):
            if not m["name"].startswith("."):
                issues.append(
                    f"Measure '{m['name']}' in '{t['name']}' does not start with '.'"
                )
    return issues


def check_measures_in_folder(tables: list[dict]) -> list[str]:
    issues = []
    for t in tables:
        if t.get("isCalculationGroup"):
            continue
        for m in t.get("measures", []):
            if not m.get("displayFolder", "").strip():
                issues.append(
                    f"Measure '{m['name']}' in '{t['name']}' has no display folder"
                )
    return issues


_SYSTEM_COL_TYPES = {"rowNumber"}

def check_columns_in_folder(tables: list[dict]) -> list[str]:
    issues = []
    for t in tables:
        if t.get("isCalculationGroup"):
            continue
        for c in t.get("columns", []):
            if c.get("type") in _SYSTEM_COL_TYPES:
                continue
            if c.get("isHidden"):
                continue  # hidden columns don't need folders
            if not c.get("displayFolder", "").strip():
                issues.append(
                    f"Column '{c['name']}' in '{t['name']}' has no display folder"
                )
    return issues


def check_descriptions(tables: list[dict]) -> list[str]:
    issues = []
    for t in tables:
        if not t.get("description", "").strip():
            issues.append(f"Table '{t['name']}' has no description")
        for m in t.get("measures", []):
            if not m.get("description", "").strip():
                issues.append(f"Measure '{m['name']}' in '{t['name']}' has no description")
        for c in t.get("columns", []):
            if c.get("type") in _SYSTEM_COL_TYPES:
                continue
            if not c.get("description", "").strip():
                issues.append(f"Column '{c['name']}' in '{t['name']}' has no description")
    return issues


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    model_dirs = find_model_dirs()
    if not model_dirs:
        print("No .SemanticModel directories found.")
        sys.exit(0)

    all_results: dict[str, dict] = {}
    failed = False

    for model_dir in model_dirs:
        print(f"\n{'='*60}\nChecking: {model_dir.name}\n{'='*60}")
        model, fmt = load_model(model_dir)
        if not model:
            print(f"  WARNING: Could not load model from {model_dir}")
            continue

        print(f"  Format: {fmt}")
        tables = model["tables"]

        results = {
            "calc_groups_prefix":  check_calc_groups(tables),
            "field_params_prefix": check_field_params(tables),
            "measure_prefix":      check_measure_prefix(tables),
            "measures_in_folder":  check_measures_in_folder(tables),
            "columns_in_folder":   check_columns_in_folder(tables),
            "descriptions":        check_descriptions(tables),
        }

        all_results[str(model_dir)] = results

        for name, issues in results.items():
            status = "PASS" if not issues else "FAIL"
            print(f"\n  [{status}] {name.replace('_', ' ').title()}")
            for issue in issues:
                print(f"    :: {issue}")
                failed = True

    Path("model-results.json").write_text(json.dumps(all_results, indent=2))
    print("\nResults written to model-results.json")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
