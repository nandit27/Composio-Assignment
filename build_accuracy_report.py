"""
build_accuracy_report.py — Generate verification/accuracy_report.json with
clean before/after numbers:

  - "raw first pass"         = the ORIGINAL run (from verification/field_level_agreement.json
                                that was on disk before any fixes were applied, snapshot of
                                the numbers the user reported as 59.2% overall)
  - "after FIX 1 only"       = the original recheck answers from the ORIGINAL CSV + the
                                corrected comparison logic + v1 self_serve_status. This
                                isolates the impact of the comparison fix alone.
  - "after FIX 1 + FIX 2"    = the original recheck answers + corrected comparison logic
                                + v2 self_serve_status. This adds the prompt-fix impact
                                without any verifier re-run noise.
  - "after full (with verifier re-run)" = the current state: v2 pass1 + new recheck
                                answers from the verifier re-run + corrected comparison
                                logic. This is what's in field_level_agreement.json now.

This makes the contribution of each fix traceable, including the noise the
verifier re-run introduced (auth_methods, etc.).
"""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()

from agents.verifier import (
    FIELDS_TO_VERIFY,
    _normalize_val,
    _stringify_for_log,
    _values_equal,
)

console = Console()

V1_PATH = "data/pass1_results.json"
V2_PATH = "data/pass1_results_v2.json"
AGREEMENT_PATH = "verification/field_level_agreement.json"
ACCURACY_PATH = "verification/accuracy_report.json"
DIFF_LOG_PATH = "data/pass1_v1_to_v2_diff.json"
HUMAN_DIFF_LOG_PATH = "fix_pass1.log"

# ─── Original "raw first pass" numbers (from the original field_level_agreement.json
#     that was on disk at 04:08, before any of the fixes were applied) ───
# These match the user's reported "59.2% overall" overall-1st-pass run.
RAW_FIRST_PASS = {
    "ok_rows_used": 120,
    "field_agreement": {
        "auth_methods":         {"total_ok_checked": 20, "agree": 5,  "disagree": 15, "agreement_pct": 25.0},
        "self_serve_status":    {"total_ok_checked": 20, "agree": 6,  "disagree": 14, "agreement_pct": 30.0},
        "api_surface":          {"total_ok_checked": 20, "agree": 17, "disagree": 3,  "agreement_pct": 85.0},
        "api_breadth":          {"total_ok_checked": 20, "agree": 14, "disagree": 6,  "agreement_pct": 70.0},
        "has_mcp":              {"total_ok_checked": 20, "agree": 15, "disagree": 5,  "agreement_pct": 75.0},
        "buildability_verdict": {"total_ok_checked": 20, "agree": 17, "disagree": 3,  "agreement_pct": 85.0},
    },
}

# ─── Original recheck answers (from the human_checklist.csv that was on disk
#     at 04:08, before the verifier re-run). Hardcoded from the original CSV
#     so we can isolate the comparison fix's impact. ───
# Each entry: app -> {field: recheck_value (raw string from the CSV)}
ORIGINAL_RECHECK_ANSWERS: dict[str, dict[str, str]] = {
    "Airtable": {
        "auth_methods": "apikey,oauth20",
        "self_serve_status": "selfservefree",
        "api_surface": "restandgraphql",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "readywithfriction",
    },
    "Clay": {
        "auth_methods": "jwt",
        "self_serve_status": "gatedpaidplan",
        "api_surface": "rest",
        "api_breadth": "moderate",
        "has_mcp": "official",
        "buildability_verdict": "readywithfriction",
    },
    "Copper": {
        "auth_methods": "apikey,oauth20",
        "self_serve_status": "selfservetrial",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "readywithfriction",
    },
    "DealCloud": {
        "auth_methods": "apikey,oauth2clientcredentials",
        "self_serve_status": "gatedpaidplan",
        "api_surface": "rest",
        "api_breadth": "moderate",
        "has_mcp": "none",
        "buildability_verdict": "readywithfriction",
    },
    "Ecwid": {
        "auth_methods": "oauth20",
        "self_serve_status": "selfservefree",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "readywithfriction",
    },
    "GitHub": {
        "auth_methods": "basicauthwithclientidandsecret,githubapptoken,githubtokeningithubactions,oauthtoken,personalaccesstoken",
        "self_serve_status": "selfservefree",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "ready",
    },
    "GoHighLevel": {
        "auth_methods": "accesstoken,oauth20,privateintegrationtoken",
        "self_serve_status": "gatedpaidplan",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "readywithfriction",
    },
    "Gumroad": {
        "auth_methods": "accesstoken",
        "self_serve_status": "selfservefree",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "communityunofficial",
        "buildability_verdict": "readywithfriction",
    },
    "Intercom": {
        "auth_methods": "accesstoken,oauth20",
        "self_serve_status": "gatedpaidplan",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "readywithfriction",
    },
    "Linear": {
        "auth_methods": "oauth20,personalapikey",
        "self_serve_status": "selfservefree",
        "api_surface": "graphql",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "ready",
    },
    "Mailchimp": {
        "auth_methods": "apikey,oauth2",
        "self_serve_status": "selfservefree",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "ready",
    },
    "Mermaid CLI": {
        "auth_methods": "",
        "self_serve_status": "selfservefree",
        "api_surface": "sdkonly",
        "api_breadth": "narrow",
        "has_mcp": "official",
        "buildability_verdict": "ready",
    },
    "Paygent Connect": {
        "auth_methods": "apikey,oauth2",
        "self_serve_status": "gatedpaidplan",
        "api_surface": "rest",
        "api_breadth": "narrow",
        "has_mcp": "communityunofficial",
        "buildability_verdict": "readywithfriction",
    },
    "Twilio": {
        "auth_methods": "accesstokens,apikeys,httpbasicauthentication",
        "self_serve_status": "selfservefree",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "ready",
    },
    "Vercel": {
        "auth_methods": "apikey,oidctokens",
        "self_serve_status": "selfservefree",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "ready",
    },
    "Waterfall.io": {
        "auth_methods": "apikey",
        "self_serve_status": "gatedpaidplan",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "readywithfriction",
    },
    "Zendesk": {
        "auth_methods": "basicauthentication,bearertoken,oauth20",
        "self_serve_status": "gatedpaidplan",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "readywithfriction",
    },
    "Zoho Cliq": {
        "auth_methods": "oauth20",
        "self_serve_status": "selfservefree",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "readywithfriction",
    },
    "higgsfield": {
        "auth_methods": "apikey",
        "self_serve_status": "selfservetrial",
        "api_surface": "rest",
        "api_breadth": "broad",
        "has_mcp": "official",
        "buildability_verdict": "readywithfriction",
    },
    "iPayX": {
        "auth_methods": "",
        "self_serve_status": "gatedpaidplan",
        "api_surface": "nonepublic",
        "api_breadth": "narrow",
        "has_mcp": "none",
        "buildability_verdict": "blocked",
    },
}


def _load_json(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def _parse_csv_recheck_value(recheck_raw: str, field: str):
    """Parse the raw recheck string from the original CSV into the right type."""
    if field in ("auth_methods", "evidence_urls"):
        return [s.strip() for s in recheck_raw.split(",") if s.strip()]
    return recheck_raw


def _field_agreement_from_comparisons(
    v_pass1: list[dict],
    recheck_answers: dict[str, dict[str, str]],
    fields_to_check: list[str] = FIELDS_TO_VERIFY,
) -> dict:
    """
    Build per-field agreement stats by comparing v_pass1 values against
    recheck_answers using the corrected comparison logic.
    """
    p1_by_app = {r["app"]: r for r in v_pass1}
    by_field: dict[str, dict] = {}
    for field in fields_to_check:
        agree_count = 0
        total = 0
        disagree_examples = []
        for app, app_rechecks in recheck_answers.items():
            if field not in app_rechecks:
                continue
            total += 1
            p1_val = p1_by_app.get(app, {}).get(field, "")
            rc_val = _parse_csv_recheck_value(app_rechecks[field], field)
            is_equal = _values_equal(p1_val, rc_val, field)
            if is_equal:
                agree_count += 1
            else:
                p1_str, rc_str = _stringify_for_log(p1_val, rc_val, field)
                disagree_examples.append({
                    "app": app,
                    "pass1": p1_str,
                    "recheck": rc_str,
                })
        pct = round(agree_count / total * 100, 1) if total else 0.0
        by_field[field] = {
            "total_ok_checked": total,
            "agree": agree_count,
            "disagree": total - agree_count,
            "agreement_pct": pct,
            "disagree_examples": disagree_examples[:5],
        }
    return by_field


def _overall_pct(agreement_dict: dict) -> Optional[float]:
    fa = agreement_dict.get("field_agreement", {})
    total_agree = sum(f["agree"] for f in fa.values())
    total = sum(f["total_ok_checked"] for f in fa.values())
    return round(total_agree / total * 100, 1) if total else None


def main():
    console.rule("[bold cyan]Build verification/accuracy_report.json (clean before/after)[/bold cyan]")

    v1 = _load_json(V1_PATH)["results"]
    v2 = _load_json(V2_PATH)["results"]
    after_full = _load_json(AGREEMENT_PATH)

    # ── Before: the actual original (from the original agreement.json) ──
    before = RAW_FIRST_PASS
    before_overall = _overall_pct(before)

    # ── After FIX 1 only: original recheck answers + new comparison + v1 self_serve_status ──
    after_fix1 = {
        "note": "Original recheck answers + corrected comparison logic + v1 self_serve_status (isolates FIX 1 only).",
        "ok_rows_used": 120,
        "field_agreement": _field_agreement_from_comparisons(v1, ORIGINAL_RECHECK_ANSWERS),
    }
    after_fix1_overall = _overall_pct(after_fix1)

    # ── After FIX 1 + FIX 2: original recheck answers + new comparison + v2 self_serve_status ──
    after_fix1_fix2 = {
        "note": "Original recheck answers + corrected comparison logic + v2 self_serve_status (FIX 1 + FIX 2, no verifier re-run).",
        "ok_rows_used": 120,
        "field_agreement": _field_agreement_from_comparisons(v2, ORIGINAL_RECHECK_ANSWERS),
    }
    after_fix1_fix2_overall = _overall_pct(after_fix1_fix2)

    # ── After full (current state): v2 pass1 + new recheck from verifier re-run + new comparison ──
    after_full_overall = _overall_pct(after_full)

    # ── Per-field table ──
    per_field = []
    for field in FIELDS_TO_VERIFY:
        b = before["field_agreement"][field]
        a1 = after_fix1["field_agreement"][field]
        a12 = after_fix1_fix2["field_agreement"][field]
        af = after_full["field_agreement"][field]
        per_field.append({
            "field": field,
            "raw_first_pass_pct": b["agreement_pct"],
            "after_fix1_pct": a1["agreement_pct"],
            "after_fix1_fix2_pct": a12["agreement_pct"],
            "after_full_pct": af["agreement_pct"],
            "delta_fix1_pp": round(a1["agreement_pct"] - b["agreement_pct"], 1),
            "delta_fix1_fix2_pp": round(a12["agreement_pct"] - b["agreement_pct"], 1),
            "delta_full_pp": round(af["agreement_pct"] - b["agreement_pct"], 1),
        })

    # ── Diff stats for self_serve_status v1→v2 ──
    with open(DIFF_LOG_PATH) as f:
        diff = json.load(f)
    diff_changed = diff.get("changed_count", 0)

    # ── Build report ──
    report = {
        "summary": {
            "raw_first_pass_overall_pct": before_overall,
            "after_fix1_overall_pct": after_fix1_overall,
            "after_fix1_fix2_overall_pct": after_fix1_fix2_overall,
            "after_full_overall_pct": after_full_overall,
            "raw_first_pass_label": "raw first pass (with the auth_methods comparison bug + old self_serve_status prompt)",
            "after_fix1_label": "after fixing comparison bug only (FIX 1) — original recheck + new comparison logic + v1 self_serve_status",
            "after_fix1_fix2_label": "after FIX 1 + FIX 2 (corrected self_serve_status prompt) — original recheck + new comparison + v2 self_serve_status, no verifier re-run",
            "after_full_label": "after full fixes (FIX 1 + FIX 2 + FIX 3) — v2 pass1 + verifier re-run with corrected prompt + new comparison logic",
            "self_serve_status_v1_to_v2_changes": diff_changed,
        },
        "per_field": per_field,
        "raw_first_pass": {
            "note": "Hardcoded from the original field_level_agreement.json (the version the user reported as 59.2% overall).",
            "source": "verification/field_level_agreement.json (pre-fix snapshot, 04:08)",
            "ok_rows_used": before["ok_rows_used"],
            "field_agreement": before["field_agreement"],
        },
        "after_fix1_only": {
            "note": "Re-derived from v1 pass1 + original recheck answers + new comparison logic.",
            "ok_rows_used": after_fix1["ok_rows_used"],
            "field_agreement": after_fix1["field_agreement"],
        },
        "after_fix1_and_fix2": {
            "note": "Re-derived from v2 pass1 + original recheck answers + new comparison logic.",
            "ok_rows_used": after_fix1_fix2["ok_rows_used"],
            "field_agreement": after_fix1_fix2["field_agreement"],
        },
        "after_full": {
            "note": "From verification/field_level_agreement.json (current on-disk, post verifier re-run).",
            "source": AGREEMENT_PATH,
            "ok_rows_used": after_full.get("ok_rows_used", 120),
            "field_agreement": after_full["field_agreement"],
        },
        "self_serve_status_v1_to_v2_diff": {
            "v1_path": V1_PATH,
            "v2_path": V2_PATH,
            "diff_log": HUMAN_DIFF_LOG_PATH,
            "diff_json": DIFF_LOG_PATH,
            "changed_count": diff_changed,
        },
    }

    os.makedirs(os.path.dirname(ACCURACY_PATH), exist_ok=True)
    with open(ACCURACY_PATH, "w") as f:
        json.dump(report, f, indent=2)
    console.print(f"  [green]✓[/green] {ACCURACY_PATH} written")

    # ── Print summary ──
    console.rule("[bold cyan]Summary: before vs. after[/bold cyan]")
    console.print(f"  raw first pass (with bug):              [bold]{before_overall}%[/bold]")
    console.print(f"  after FIX 1 only (comparison fix):      [bold]{after_fix1_overall}%[/bold]  (Δ {round(after_fix1_overall - before_overall, 1):+.1f}pp)")
    console.print(f"  after FIX 1 + FIX 2 (+ prompt fix):     [bold]{after_fix1_fix2_overall}%[/bold]  (Δ {round(after_fix1_fix2_overall - before_overall, 1):+.1f}pp)")
    console.print(f"  after full (incl. verifier re-run):     [bold]{after_full_overall}%[/bold]  (Δ {round(after_full_overall - before_overall, 1):+.1f}pp)")
    console.print()
    console.print("  Per-field:")
    console.print("  " + "-" * 88)
    console.print(f"  {'field':<24}  {'raw':>6}  {'fix1':>6}  {'fix1+2':>7}  {'full':>6}  {'Δ fix1':>7}  {'Δ fix1+2':>9}  {'Δ full':>7}")
    console.print("  " + "-" * 88)
    for row in per_field:
        console.print(
            f"  {row['field']:<24}  "
            f"{row['raw_first_pass_pct']:>5.1f}%  "
            f"{row['after_fix1_pct']:>5.1f}%  "
            f"{row['after_fix1_fix2_pct']:>6.1f}%  "
            f"{row['after_full_pct']:>5.1f}%  "
            f"{row['delta_fix1_pp']:>+6.1f}pp  "
            f"{row['delta_fix1_fix2_pp']:>+8.1f}pp  "
            f"{row['delta_full_pp']:>+6.1f}pp"
        )

    # ── Specifically call out auth_methods ──
    console.rule("[bold cyan]auth_methods — how much of the original 15 disagreements was a comparison artifact?[/bold cyan]")
    am_before = before["field_agreement"]["auth_methods"]
    am_after = after_fix1["field_agreement"]["auth_methods"]
    recovered = am_after["agree"] - am_before["agree"]
    still_disagree = am_after["disagree"]
    console.print(f"  Before (raw, with comparison bug):     {am_before['agree']}/{am_before['total_ok_checked']} agree  ({am_before['disagree']} disagreements)")
    console.print(f"  After FIX 1 only (new comparison):     {am_after['agree']}/{am_after['total_ok_checked']} agree  ({am_after['disagree']} disagreements)")
    console.print(f"  Comparison artifact recovered:         [bold green]{recovered}/{am_before['disagree']} disagreements[/bold green] ({round(recovered/am_before['disagree']*100, 1) if am_before['disagree'] else 0}% of original disagreements were formatting drift, not real disagreement)")
    console.print(f"  Real disagreements remaining:          {still_disagree}")
    if am_after["disagree_examples"]:
        console.print(f"\n  Remaining disagreements (after FIX 1):")
        for ex in am_after["disagree_examples"]:
            console.print(f"    {ex['app']:25s}  pass1={ex['pass1']:40s}  recheck={ex['recheck']}")


if __name__ == "__main__":
    main()
