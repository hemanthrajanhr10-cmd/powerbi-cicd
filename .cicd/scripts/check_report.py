"""
Report checks:
  1. Filter pane closed
  2. Buttons / shapes have bookmark actions
  3. Object IDs meaningfully renamed (not default hashes)
  4. No broken visuals (data-bound visuals with no query)
  5. Consistent spacing between visuals (≤5 px deviation)
  6. Theme matches approved list (APPROVED_THEMES env var, comma-separated)
"""

import glob
import json
import os
import re
import sys
from pathlib import Path

# ── helpers ────────────────────────────────────────────────────────────────────

def _parse(value) -> dict:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return {}
    return value or {}


def find_report_dirs() -> list[Path]:
    paths_env = os.environ.get("REPORT_PATHS", "").strip()
    if paths_env:
        dirs = [p.strip() for p in paths_env.split(",") if p.strip()]
    else:
        dirs = glob.glob("*.Report")
    return [Path(d) for d in dirs if Path(d).is_dir()]


def load_report_json(report_dir: Path) -> dict:
    for candidate in [
        report_dir / "definition" / "report.json",
        report_dir / "report.json",
        report_dir / "definition.pbr",
    ]:
        if candidate.exists():
            return json.loads(candidate.read_text(encoding="utf-8"))
    return {}


def load_pages(report_dir: Path) -> list[dict]:
    pages = []
    for pages_dir in [
        report_dir / "definition" / "pages",
        report_dir / "pages",
    ]:
        if pages_dir.is_dir():
            for f in pages_dir.glob("*.json"):
                try:
                    pages.append(json.loads(f.read_text(encoding="utf-8")))
                except Exception:
                    pass
    return pages


def all_visuals(pages: list[dict]) -> list[dict]:
    return [v for page in pages for v in page.get("visualContainers", [])]


# ── checks ─────────────────────────────────────────────────────────────────────

_DEFAULT_ID = re.compile(
    r"^ReportSection[a-f0-9]{4,}$"
    r"|^[a-f0-9]{20,}$"
    r"|^\d+$"
    r"|^Visual\d+$",
    re.IGNORECASE,
)

_BUTTON_TYPES = {"actionButton", "image", "shape", "basicShape"}
_NON_DATA_TYPES = {"textbox", "image", "shape", "actionButton", "basicShape", "slicer"}


def check_filter_pane(report_json: dict) -> list[str]:
    config = _parse(report_json.get("config", {}))
    if config.get("filterPaneEnabled", True):
        return ["Filter pane is not disabled at report level"]
    return []


def check_buttons_without_bookmarks(visuals: list[dict]) -> list[str]:
    issues = []
    for v in visuals:
        cfg = _parse(v.get("config", {}))
        sv = cfg.get("singleVisual", {})
        if sv.get("visualType") not in _BUTTON_TYPES:
            continue
        # Look for a bookmark action in objects.general
        has_bookmark = False
        for entry in sv.get("objects", {}).get("general", []):
            action = entry.get("properties", {}).get("action", {})
            action_type = (
                action.get("actionType", {})
                .get("expr", {})
                .get("Literal", {})
                .get("Value", "")
            )
            if action_type in ("'Bookmark'", "Bookmark"):
                has_bookmark = True
                break
        if not has_bookmark:
            label = sv.get("title") or v.get("name", "unnamed")
            issues.append(
                f"Button/shape '{label}' (type: {sv.get('visualType')}) has no bookmark action"
            )
    return issues


def check_object_ids(visuals: list[dict], pages: list[dict]) -> list[str]:
    issues = []
    for page in pages:
        name = page.get("name", "")
        if _DEFAULT_ID.match(name):
            issues.append(
                f"Page '{page.get('displayName', name)}' has a default/unrenamed ID: '{name}'"
            )
    for v in visuals:
        name = v.get("name", "")
        if _DEFAULT_ID.match(name):
            cfg = _parse(v.get("config", {}))
            vtype = cfg.get("singleVisual", {}).get("visualType", "unknown")
            issues.append(f"Visual of type '{vtype}' has default/unrenamed ID: '{name}'")
    return issues


def check_broken_visuals(visuals: list[dict]) -> list[str]:
    issues = []
    for v in visuals:
        cfg = _parse(v.get("config", {}))
        sv = cfg.get("singleVisual", {})
        vtype = sv.get("visualType", "")
        if not vtype or vtype in _NON_DATA_TYPES:
            continue
        has_query = bool(sv.get("prototypeQuery") or sv.get("projections") or sv.get("dataRoles"))
        if not has_query:
            issues.append(
                f"Visual '{v.get('name', 'unnamed')}' ({vtype}) has no data binding — may be broken"
            )
    return issues


def check_spacing(visuals: list[dict], tolerance: int = 5) -> list[str]:
    """Flag pages where horizontal or vertical gaps between visuals are inconsistent."""
    issues = []
    if len(visuals) < 3:
        return issues

    def gaps(sorted_visuals, pos_key, size_key):
        result = []
        for i in range(len(sorted_visuals) - 1):
            a, b = sorted_visuals[i], sorted_visuals[i + 1]
            gap = b.get(pos_key, 0) - (a.get(pos_key, 0) + a.get(size_key, 0))
            if 0 < gap < 500:
                result.append((i, gap))
        return result

    by_x = sorted(visuals, key=lambda v: v.get("x", 0))
    by_y = sorted(visuals, key=lambda v: v.get("y", 0))

    for axis_label, axis_gaps in [("horizontal", gaps(by_x, "x", "width")),
                                   ("vertical",   gaps(by_y, "y", "height"))]:
        if not axis_gaps:
            continue
        avg = sum(g for _, g in axis_gaps) / len(axis_gaps)
        for idx, g in axis_gaps:
            if abs(g - avg) > tolerance:
                issues.append(
                    f"Inconsistent {axis_label} gap: {g:.0f}px between visual {idx+1} and {idx+2} "
                    f"(avg {avg:.0f}px, tolerance ±{tolerance}px)"
                )
    return issues


def check_template_adherence(report_json: dict) -> list[str]:
    approved_raw = os.environ.get("APPROVED_THEMES", "").strip()
    if not approved_raw:
        return []  # skip if no approved list configured

    approved = {t.strip() for t in approved_raw.split(",") if t.strip()}
    config = _parse(report_json.get("config", {}))
    theme_name = (
        report_json.get("theme")
        or config.get("theme", {}).get("name", "")
        or config.get("themeCollection", {}).get("baseTheme", {}).get("name", "")
    )

    if theme_name not in approved:
        return [
            f"Theme '{theme_name or '(none)'}' is not in the approved list: {sorted(approved)}"
        ]
    return []


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    report_dirs = find_report_dirs()
    if not report_dirs:
        print("No .Report directories found.")
        sys.exit(0)

    all_results: dict[str, dict] = {}
    failed = False

    for report_dir in report_dirs:
        print(f"\n{'='*60}\nChecking: {report_dir.name}\n{'='*60}")
        report_json = load_report_json(report_dir)
        pages = load_pages(report_dir)
        visuals = all_visuals(pages)

        results = {
            "filter_pane":              check_filter_pane(report_json),
            "buttons_without_bookmarks": check_buttons_without_bookmarks(visuals),
            "object_ids_renamed":       check_object_ids(visuals, pages),
            "broken_visuals":           check_broken_visuals(visuals),
            "consistent_spacing":       check_spacing(visuals),
            "template_adherence":       check_template_adherence(report_json),
        }

        all_results[str(report_dir)] = results

        for name, issues in results.items():
            status = "PASS" if not issues else "FAIL"
            print(f"\n  [{status}] {name.replace('_', ' ').title()}")
            for issue in issues:
                print(f"    :: {issue}")
                failed = True

    Path("report-results.json").write_text(json.dumps(all_results, indent=2))
    print("\nResults written to report-results.json")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
