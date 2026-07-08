"""
Pattern Analyzer
Computes statistical patterns from final_results.json and generates
headline insights for the case study HTML page.
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from typing import Any

from rich.console import Console

console = Console()


def run_pattern_analysis(
    final_results_path: str = "data/final_results.json",
    composio_crosscheck_path: str = "data/composio_crosscheck.json",
    output_path: str = "data/patterns.json",
) -> dict:
    console.rule("[bold cyan]Pattern Analysis[/bold cyan]")

    with open(final_results_path) as f:
        final_data = json.load(f)
    results = final_data["results"]

    with open(composio_crosscheck_path) as f:
        cc_data = json.load(f)
    composio_results = cc_data["results"]
    composio_coverage = cc_data["meta"].get("composio_coverage_pct", 0)
    composio_found = cc_data["meta"].get("found_in_composio", 0)

    # ── Auth method distribution ──────────────────────────────────────────
    all_auth_methods = []
    auth_by_category: dict[str, Counter] = defaultdict(Counter)
    for r in results:
        methods = r.get("auth_methods", [])
        if not isinstance(methods, list):
            methods = [methods]
        for m in methods:
            if m:
                all_auth_methods.append(str(m).lower())
                auth_by_category[r.get("category", "Unknown")][str(m).lower()] += 1

    auth_overall = dict(Counter(all_auth_methods).most_common())
    auth_by_cat = {cat: dict(counter.most_common()) for cat, counter in auth_by_category.items()}

    # ── Self-serve vs gated breakdown ────────────────────────────────────
    SELF_SERVE = {"self_serve_free", "self_serve_trial", "open_source_self_host"}
    GATED = {"gated_paid_plan", "gated_approval", "gated_partnership"}

    ss_overall = Counter()
    ss_by_category: dict[str, dict] = defaultdict(lambda: {"self_serve": 0, "gated": 0, "total": 0})
    status_distribution = Counter()

    for r in results:
        status = r.get("self_serve_status", "")
        status_distribution[status] += 1
        cat = r.get("category", "Unknown")
        ss_by_category[cat]["total"] += 1

        if status in SELF_SERVE:
            ss_overall["self_serve"] += 1
            ss_by_category[cat]["self_serve"] += 1
        elif status in GATED:
            ss_overall["gated"] += 1
            ss_by_category[cat]["gated"] += 1

    # Compute pcts per category
    for cat, vals in ss_by_category.items():
        total = vals["total"]
        vals["self_serve_pct"] = round(vals["self_serve"] / total * 100, 1) if total else 0
        vals["gated_pct"] = round(vals["gated"] / total * 100, 1) if total else 0

    ss_overall_pct = {
        "self_serve": ss_overall["self_serve"],
        "gated": ss_overall["gated"],
        "self_serve_pct": round(ss_overall["self_serve"] / len(results) * 100, 1) if results else 0,
        "gated_pct": round(ss_overall["gated"] / len(results) * 100, 1) if results else 0,
    }
    ss_by_cat_serializable = {cat: dict(vals) for cat, vals in ss_by_category.items()}

    # ── Buildability verdict distribution ────────────────────────────────
    verdict_dist = Counter(r.get("buildability_verdict", "unknown") for r in results)
    verdict_by_category = defaultdict(Counter)
    for r in results:
        verdict_by_category[r.get("category", "Unknown")][r.get("buildability_verdict", "unknown")] += 1

    # ── Most common blockers ──────────────────────────────────────────────
    blockers = [
        r.get("main_blocker", "none")
        for r in results
        if r.get("main_blocker", "none") not in ("none", "None", "", None)
    ]
    # Categorize blockers
    blocker_categories = Counter()
    for b in blockers:
        b_lower = str(b).lower()
        if any(kw in b_lower for kw in ["enterprise", "partner", "approval", "apply"]):
            blocker_categories["Enterprise/partner approval required"] += 1
        elif any(kw in b_lower for kw in ["paid", "subscription", "plan", "pricing"]):
            blocker_categories["Paid plan required for API access"] += 1
        elif any(kw in b_lower for kw in ["no api", "no public", "none_public", "no rest"]):
            blocker_categories["No public API available"] += 1
        elif any(kw in b_lower for kw in ["limited", "narrow", "few endpoint", "scope"]):
            blocker_categories["Very limited API scope"] += 1
        elif any(kw in b_lower for kw in ["block", "js", "scrape", "403", "captcha"]):
            blocker_categories["Blocked / JS-only (research blocked)"] += 1
        elif any(kw in b_lower for kw in ["error", "failed", "research"]):
            blocker_categories["Research error (could not verify)"] += 1
        else:
            blocker_categories["Other / complex auth requirements"] += 1

    blockers_ranked = [{"blocker": k, "count": v} for k, v in blocker_categories.most_common()]

    # ── API surface distribution ──────────────────────────────────────────
    api_surface_dist = dict(Counter(r.get("api_surface", "unknown") for r in results).most_common())

    # ── MCP distribution ──────────────────────────────────────────────────
    mcp_dist = dict(Counter(r.get("has_mcp", "unknown") for r in results).most_common())

    # ── Category outliers ─────────────────────────────────────────────────
    cat_stats = {}
    for cat, vals in ss_by_category.items():
        total = vals["total"]
        ready_count = verdict_by_category[cat].get("ready", 0)
        cat_stats[cat] = {
            "self_serve_pct": vals["self_serve_pct"],
            "gated_pct": vals["gated_pct"],
            "ready_pct": round(ready_count / total * 100, 1) if total else 0,
            "total": total,
        }

    most_self_serve = max(cat_stats.items(), key=lambda x: x[1]["self_serve_pct"])
    most_gated = max(cat_stats.items(), key=lambda x: x[1]["gated_pct"])
    most_ready = max(cat_stats.items(), key=lambda x: x[1]["ready_pct"])

    # ── Headline insights ─────────────────────────────────────────────────
    ready_count = verdict_dist.get("ready", 0)
    ready_friction_count = verdict_dist.get("ready_with_friction", 0)
    blocked_count = verdict_dist.get("blocked", 0)
    self_serve_count = ss_overall["self_serve"]
    gated_count = ss_overall["gated"]
    oauth2_count = auth_overall.get("oauth2", 0)
    api_key_count = auth_overall.get("api_key", 0)
    mcp_official = mcp_dist.get("official", 0)
    mcp_community = mcp_dist.get("community_unofficial", 0)

    insights = [
        f"{ready_count + ready_friction_count} of 100 apps ({ready_count + ready_friction_count}%) have a usable API — but only {ready_count} are immediately 'ready' with no friction, meaning {ready_friction_count} require overcoming paid-plan or auth barriers.",
        f"The self-serve vs. gated split is striking: {self_serve_count}% of apps offer self-serve API access (free or trial), while {gated_count}% are gated behind approvals, paid plans, or enterprise partnerships.",
        f"OAuth 2.0 ({oauth2_count} apps) and API Key ({api_key_count} apps) dominate auth — together covering {oauth2_count + api_key_count}% of the catalog, making standard Composio-style connector patterns directly applicable to most.",
        f"{most_self_serve[0]} is the most self-serve-friendly category ({most_self_serve[1]['self_serve_pct']}% self-serve), while {most_gated[0]} is the most gated ({most_gated[1]['gated_pct']}% gated) — a key segmentation signal for toolkit prioritization.",
        f"MCP (Model Context Protocol) adoption is early but real: {mcp_official} apps have official MCP servers and {mcp_community} have community-built ones — these are already agent-ready without any additional connector work.",
        f"Composio already covers {composio_found} of 100 apps ({composio_coverage}% of this catalog), leaving {100 - composio_found} apps as potential expansion opportunities for new toolkit builders.",
    ]

    patterns = {
        "total_apps": len(results),
        "auth_method_distribution": {
            "overall": auth_overall,
            "by_category": auth_by_cat,
        },
        "self_serve_vs_gated": {
            "overall": ss_overall_pct,
            "status_distribution": dict(status_distribution),
            "by_category": ss_by_cat_serializable,
        },
        "buildability_verdicts": {
            "overall": dict(verdict_dist),
            "by_category": {cat: dict(c) for cat, c in verdict_by_category.items()},
        },
        "blockers_ranked": blockers_ranked,
        "api_surface_distribution": api_surface_dist,
        "mcp_distribution": mcp_dist,
        "composio_coverage": {
            "found_in_composio": composio_found,
            "total_apps": len(results),
            "coverage_pct": composio_coverage,
            "not_in_composio": 100 - composio_found,
        },
        "category_outliers": {
            "most_self_serve": {"category": most_self_serve[0], **most_self_serve[1]},
            "most_gated": {"category": most_gated[0], **most_gated[1]},
            "most_buildability_ready": {"category": most_ready[0], **most_ready[1]},
        },
        "category_stats": cat_stats,
        "headline_insights": insights,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(patterns, f, indent=2)

    console.print(f"[bold green]Pattern analysis complete![/bold green]")
    console.print(f"  Saved → {output_path}")
    console.print("\n[bold]Headline Insights:[/bold]")
    for i, insight in enumerate(insights, 1):
        console.print(f"  {i}. {insight}")

    return patterns
