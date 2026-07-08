"""
Accuracy Computer
Ingests the human-filled checklist CSV, computes field-level accuracy
(Pass 1 vs human-corrected), applies systematic corrections to all 100 records,
and saves final_results.json and accuracy_report.json.
"""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from typing import Optional

from rich.console import Console

console = Console()


def load_checklist(checklist_path: str = "verification/human_checklist.csv") -> list[dict]:
    """Load the human-filled checklist CSV."""
    rows = []
    with open(checklist_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def compute_accuracy(
    checklist_rows: list[dict],
    pass1_results: list[dict],
    composio_crosscheck: list[dict],
    output_dir: str = "verification",
    final_output_path: str = "data/final_results.json",
) -> dict:
    """
    Compute field-level accuracy and apply systematic corrections.
    Returns the accuracy report dict.
    """

    # Group checklist by field — EXCLUDE rows where recheck failed
    by_field: dict[str, list[dict]] = defaultdict(list)
    skipped_recheck_failed = 0
    for row in checklist_rows:
        field = row.get("field", "")
        human_answer = row.get("human_verified_correct_answer", "").strip()
        recheck_ok = row.get("recheck_status", "ok") == "ok"
        if not recheck_ok:
            skipped_recheck_failed += 1
            continue  # don't count failed rechecks as evidence Pass 1 was wrong
        if human_answer:  # Only count rows where human filled in an answer
            by_field[field].append(row)

    if skipped_recheck_failed:
        console.print(f"[yellow]  ℹ  Skipped {skipped_recheck_failed} rows with recheck_status != 'ok' from accuracy computation[/yellow]")

    # Compute per-field accuracy
    field_accuracy = {}
    systematic_corrections: dict[str, dict] = {}  # field -> {wrong_value: correct_value}

    for field, rows in by_field.items():
        total = len(rows)
        pass1_correct = 0
        pass1_corrections = defaultdict(lambda: defaultdict(int))  # {wrong: {correct: count}}

        for row in rows:
            pass1_val = row.get("pass1_answer", "").strip().lower()
            human_val = row.get("human_verified_correct_answer", "").strip().lower()

            if pass1_val == human_val:
                pass1_correct += 1
            else:
                pass1_corrections[pass1_val][human_val] += 1

        pass1_acc = round(pass1_correct / total * 100, 1) if total > 0 else 100.0

        # Identify systematic errors (same wrong→right pattern 2+ times)
        sys_errors = {}
        for wrong_val, corrections in pass1_corrections.items():
            for right_val, count in corrections.items():
                if count >= 2:
                    sys_errors[wrong_val] = right_val

        field_accuracy[field] = {
            "total_checked": total,
            "pass1_correct": pass1_correct,
            "pass1_accuracy_pct": pass1_acc,
            "systematic_errors": sys_errors,
        }

        if sys_errors:
            systematic_corrections[field] = sys_errors
            console.print(f"  [yellow]Systematic error in '{field}':[/yellow] {sys_errors}")

    # Overall accuracy (across all checked fields)
    total_checks = sum(v["total_checked"] for v in field_accuracy.values())
    total_correct = sum(v["pass1_correct"] for v in field_accuracy.values())
    overall_pass1_acc = round(total_correct / total_checks * 100, 1) if total_checks > 0 else 100.0

    # Apply systematic corrections to all 100 records
    corrected_results = []
    corrections_applied = 0

    for record in pass1_results:
        corrected = dict(record)

        for field, corrections in systematic_corrections.items():
            current_val = corrected.get(field)

            if isinstance(current_val, list):
                new_val = []
                changed = False
                for item in current_val:
                    if str(item).lower() in corrections:
                        new_val.append(corrections[str(item).lower()])
                        changed = True
                    else:
                        new_val.append(item)
                if changed:
                    corrected[field] = new_val
                    corrections_applied += 1
            elif isinstance(current_val, str):
                if current_val.lower() in corrections:
                    corrected[field] = corrections[current_val.lower()]
                    corrections_applied += 1

        # Also apply individual human corrections for the sampled apps
        # (not just systematic ones)
        for row in checklist_rows:
            if row.get("app") == record.get("app"):
                field = row.get("field", "")
                human_answer = row.get("human_verified_correct_answer", "").strip()
                if human_answer and field:
                    pass1_val = str(record.get(field, "")).lower()
                    if pass1_val != human_answer.lower():
                        # Apply individual correction
                        if isinstance(record.get(field), list):
                            corrected[field] = [human_answer]
                        else:
                            corrected[field] = human_answer

        corrected["human_verified"] = record["app"] in {row["app"] for row in checklist_rows}
        corrected_results.append(corrected)

    # Build accuracy report
    report = {
        "summary": {
            "total_apps_in_sample": len({row["app"] for row in checklist_rows}),
            "total_field_checks": total_checks,
            "pass1_overall_accuracy_pct": overall_pass1_acc,
            "systematic_corrections_applied_to_full_dataset": corrections_applied,
        },
        "field_level_accuracy": field_accuracy,
        "systematic_corrections": systematic_corrections,
    }

    # Save accuracy report
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "accuracy_report.json"), "w") as f:
        json.dump(report, f, indent=2)

    # Save final results
    os.makedirs(os.path.dirname(final_output_path), exist_ok=True)

    # Merge composio crosscheck data into final results
    composio_lookup = {r["app"]: r for r in composio_crosscheck}
    for record in corrected_results:
        cc = composio_lookup.get(record["app"], {})
        record["exists_in_composio"] = cc.get("exists_in_composio", "not_checked")
        record["composio_tool_count"] = cc.get("composio_tool_count", None)
        record["composio_url"] = cc.get("composio_url", None)

    with open(final_output_path, "w") as f:
        json.dump({"results": corrected_results}, f, indent=2)

    console.print(f"\n[bold green]Accuracy computation complete![/bold green]")
    console.print(f"  Pass 1 overall accuracy: [bold]{overall_pass1_acc}%[/bold] ({total_correct}/{total_checks} fields correct)")
    console.print(f"  Systematic corrections applied to full dataset: {corrections_applied}")
    console.print(f"  Saved → verification/accuracy_report.json")
    console.print(f"  Saved → {final_output_path}\n")

    return report


def compute_accuracy_no_human(
    pass1_results: list[dict],
    composio_crosscheck: list[dict],
    final_output_path: str = "data/final_results.json",
    output_dir: str = "verification",
) -> dict:
    """
    Fallback: if no human checklist is filled in, just copy pass1 to final.
    This produces an accuracy report with "not_computed" fields.
    """
    report = {
        "summary": {
            "total_apps_in_sample": 0,
            "total_field_checks": 0,
            "pass1_overall_accuracy_pct": "not_computed (human checklist not filled)",
            "systematic_corrections_applied_to_full_dataset": 0,
        },
        "field_level_accuracy": {},
        "systematic_corrections": {},
        "note": "Human checklist was not filled in. Pass 1 results used directly as final results.",
    }

    # Merge composio data into results
    composio_lookup = {r["app"]: r for r in composio_crosscheck}
    final = []
    for record in pass1_results:
        rec = dict(record)
        cc = composio_lookup.get(record["app"], {})
        rec["exists_in_composio"] = cc.get("exists_in_composio", "not_checked")
        rec["composio_tool_count"] = cc.get("composio_tool_count", None)
        rec["composio_url"] = cc.get("composio_url", None)
        rec["human_verified"] = False
        final.append(rec)

    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "accuracy_report.json"), "w") as f:
        json.dump(report, f, indent=2)

    os.makedirs(os.path.dirname(final_output_path), exist_ok=True)
    with open(final_output_path, "w") as f:
        json.dump({"results": final}, f, indent=2)

    return report
