"""
Agent 3: Verifier + Human Checklist
Stratified random sample of 20 apps, re-researches with an alternative query
strategy, compares vs Pass 1, and generates a human checklist CSV.

Improvements over v1:
- Per-app and per-stage error logging (search vs. fetch vs. parse failure)
- 3-attempt exponential backoff around Tavily search and OpenAI structured output
- recheck_status column: ok | degraded | failed
- Failed re-checks are NOT presented as disagreements
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import random
import re
import time
from collections import defaultdict
from typing import Optional

from rich.console import Console

console = Console()

FIELDS_TO_VERIFY = [
    "auth_methods",
    "self_serve_status",
    "api_surface",
    "api_breadth",
    "has_mcp",
    "buildability_verdict",
]

ALTERNATIVE_SYSTEM_PROMPT = """You are a technical API researcher verifying data about SaaS apps.

Use a DIFFERENT search approach: focus on:
1. Official developer documentation pages (search: site:<domain> API OR developer OR auth)
2. API changelog or status pages
3. GitHub repositories for official SDKs
4. Dev.to / Medium articles by the company about their API

Return ONLY a raw JSON object with these EXACT fields:
{
  "id": <integer>,
  "app": "<name>",
  "category": "<category>",
  "one_liner": "<1 sentence>",
  "auth_methods": ["<method>"],
  "self_serve_status": "<enum>",
  "gating_evidence_note": "<note>",
  "api_surface": "<enum>",
  "api_breadth": "<enum>",
  "has_mcp": "<enum>",
  "buildability_verdict": "<enum>",
  "main_blocker": "<string or 'none'>",
  "evidence_urls": ["<url>"],
  "confidence": "<enum>"
}

Valid enums:
- self_serve_status: self_serve_free | self_serve_trial | gated_paid_plan | gated_approval | gated_partnership | open_source_self_host
- api_surface: rest | graphql | rest_and_graphql | sdk_only | none_public
- api_breadth: broad | moderate | narrow
- has_mcp: official | community_unofficial | none | unknown
- buildability_verdict: ready | ready_with_friction | blocked
- confidence: high | medium | low

CRITICAL — definition of self_serve_status:
This field describes whether a developer can obtain WORKING API CREDENTIALS
today for free or on a trial — independent of whether the product's OTHER
(non-API) features are paywalled.

- self_serve_free: any developer can sign up (free plan or trial that does
  not require payment) and immediately generate a functional API key,
  OAuth app, or other API credential with no human approval step. Even if
  the product's premium FEATURES (storage, seats, advanced modules) are
  paywalled, if the API key/OAuth app itself can be generated for free,
  this is self_serve_free.
- self_serve_trial: a free trial account (time- or usage-limited) can
  generate working API credentials, but the credentials expire or stop
  working when the trial ends unless the developer converts to a paid
  plan.
- gated_paid_plan: obtaining API credentials itself requires an active
  paid subscription (not just a trial) — i.e. the API layer, not just
  other product features, is paywalled. Use this only when the developer
  cannot get working API keys at all without paying.
- gated_approval: must apply/request access (human approval process)
- gated_partnership: enterprise/partner program required
- open_source_self_host: open source, primarily self-hosted

When unsure, err on the side of "can a brand-new free or trial account
generate an API key right now, end-to-end, with no payment?" — if yes,
it's self_serve_free or self_serve_trial, NOT gated_paid_plan.

Return ONLY the JSON, no markdown, no explanation."""


def _stratified_sample(pass1_results: list[dict], n: int = 20) -> list[dict]:
    """
    Stratified random sample: ≥2 per category, weighted toward low-confidence.
    """
    by_category: dict[str, list] = defaultdict(list)
    for r in pass1_results:
        by_category[r.get("category", "Unknown")].append(r)

    sampled: list[dict] = []
    for cat in by_category:
        cat_apps = sorted(
            by_category[cat],
            key=lambda x: {"low": 0, "medium": 1, "high": 2}.get(x.get("confidence", "medium"), 1),
        )
        sampled.extend(cat_apps[:2])

    already_ids = {r["id"] for r in sampled}
    remaining = sorted(
        [r for r in pass1_results if r["id"] not in already_ids],
        key=lambda x: {"low": 0, "medium": 1, "high": 2}.get(x.get("confidence", "medium"), 1),
    )
    need = n - len(sampled)
    if need > 0 and remaining:
        cutoff = max(need, int(len(remaining) * 0.6))
        extra = random.sample(remaining[:cutoff], min(need, len(remaining[:cutoff])))
        sampled.extend(extra)

    random.shuffle(sampled)
    return sampled[:n]


# Fields whose values are *lists* (vs. scalar enums) — these are compared as
# normalized sets so ordering and token-level formatting drift (e.g.
# "OAuth 2.0" vs "oauth2" vs "oauth_2") don't count as a real disagreement.
LIST_FIELDS = {"auth_methods", "evidence_urls"}

# Fields whose values are scalar enums that may also have format drift
# (e.g. "OAuth 2.0" vs "oauth2" — uncommon, but possible). We apply the
# same normalization to these so any silent drift is surfaced.
ENUM_FIELDS = {
    "self_serve_status",
    "api_surface",
    "api_breadth",
    "has_mcp",
    "buildability_verdict",
    "confidence",
}


def _normalize_token(token) -> str:
    """
    Normalize a single token for comparison.

    Steps (in order):
      1. Lowercase.
      2. Strip every non-alphanumeric character (spaces, underscores,
         dashes, dots, slashes, etc.) so 'OAuth 2.0', 'oauth2', 'oauth_2',
         and 'oauth 2' all collapse to the same key.
      3. Collapse version-number trailing zeros: 'oauth20' -> 'oauth2'
         and 'X1.0' -> 'X10' -> 'X1'. This handles the common case where
         'OAuth 2.0' (pass1) and 'oauth20' (recheck, post-strip) refer to
         the same major version.

    The user-facing example: 'OAuth 2.0' and 'oauth2' and 'oauth_2' must
    all collapse to the same token. Following steps 1-3 above:
      'OAuth 2.0' -> 'oauth20' -> 'oauth2'   ✓
      'oauth2'    -> 'oauth2'                ✓
      'oauth_2'   -> 'oauth2'                ✓
    """
    if token is None:
        return ""
    s = str(token).lower().strip()
    # Step 2: keep only alphanumerics (strips spaces, underscores, dashes, dots, slashes).
    s = "".join(ch for ch in s if ch.isalnum())
    # Step 3: strip trailing '0' that immediately follows a digit, so
    # 'X.0' / 'X20' / 'X100' all collapse to the same 'X' (and 'X2'
    # stays 'X2'). This is what makes 'OAuth 2.0' (after step 2 = 'oauth20')
    # match the canonical 'oauth2'.
    while len(s) > 1 and s[-1] == "0" and s[-2].isdigit():
        s = s[:-1]
    return s


def _normalize_val(val, field: str = "") -> object:
    """
    Normalize a value for comparison. For list fields, returns a frozenset of
    normalized tokens so order/format drift doesn't cause spurious
    disagreements. For scalar fields, returns the normalized string.
    """
    if isinstance(val, list):
        tokens = {_normalize_token(v) for v in val if v}
        tokens.discard("")
        return frozenset(tokens)
    return _normalize_token(val)


def _values_equal(p1, rc, field: str) -> bool:
    """Field-aware equality after normalization."""
    if field in LIST_FIELDS:
        return _normalize_val(p1, field) == _normalize_val(rc, field)
    return _normalize_val(p1, field) == _normalize_val(rc, field)


def _stringify_for_log(p1, rc, field: str) -> tuple[str, str]:
    """Stable, human-readable string form of each value for the disagreement log."""
    p_norm = _normalize_val(p1, field)
    rc_norm = _normalize_val(rc, field)
    if isinstance(p_norm, frozenset):
        p_str = ",".join(sorted(p_norm))
    else:
        p_str = p_norm
    if isinstance(rc_norm, frozenset):
        rc_str = ",".join(sorted(rc_norm))
    else:
        rc_str = rc_norm
    return p_str, rc_str


def _compare_fields(pass1: dict, recheck: dict) -> dict:
    """Compare fields between pass1 and recheck results using normalized comparison."""
    comparison = {}
    for field in FIELDS_TO_VERIFY:
        p1_val = pass1.get(field)
        rc_val = recheck.get(field)
        p1_str, rc_str = _stringify_for_log(p1_val, rc_val, field)
        comparison[field] = {
            "pass1": p1_str,
            "recheck": rc_str,
            "agree": _values_equal(p1_val, rc_val, field),
        }
    return comparison


async def _recheck_single_app(
    app_record: dict,
    hint: str,
    agent,
    semaphore: asyncio.Semaphore,
) -> dict:
    """
    Re-check a single app with retry logic.
    Returns: {status: ok|degraded|failed, data: dict, failure_stages: list}
    """
    from agents.researcher import extract_json_from_response, fetch_page

    app_name = app_record["app"]
    failure_stages = []
    last_error = None

    async with semaphore:
        for attempt in range(1, 4):  # 3 attempts with backoff
            try:
                prompt = (
                    f"Independently verify this app's API buildability:\n"
                    f"App: {app_name}\n"
                    f"Category: {app_record.get('category', '')}\n"
                    f"Docs hint: {hint}\n\n"
                    f"Use these ALTERNATIVE search queries:\n"
                    f'1. site:github.com "{app_name}" API SDK\n'
                    f'2. "{app_name}" developer docs authentication REST\n'
                    f'3. "{app_name}" API access pricing self-serve\n\n'
                    f"Return only the JSON object."
                )

                # Run agent call in thread (it's sync)
                response = await asyncio.to_thread(agent.run, prompt)
                raw = response.content if hasattr(response, "content") else str(response)

                # Parse JSON
                data = extract_json_from_response(raw)
                if data is None:
                    raise ValueError(f"JSON parse failed. Raw (first 300 chars): {raw[:300]}")

                # Ensure required fields
                data.setdefault("id", app_record.get("id"))
                data.setdefault("app", app_name)
                data.setdefault("category", app_record.get("category", ""))

                console.print(f"  [green]✓[/green] {app_name} (attempt {attempt})")
                return {"status": "ok", "data": data, "failure_stages": []}

            except Exception as e:
                last_error = str(e)
                failure_stages.append({
                    "attempt": attempt,
                    "error_type": type(e).__name__,
                    "error": str(e)[:400],
                })
                console.print(f"  [yellow]⚠ {app_name} attempt {attempt} failed: {type(e).__name__}: {str(e)[:80]}[/yellow]")

                if attempt < 3:
                    backoff = 2 ** attempt  # 2s, 4s
                    await asyncio.sleep(backoff)

        # All 3 attempts failed — mark as degraded and use pass1 as fallback
        console.print(f"  [red]✗ {app_name} — all 3 attempts failed. Using Pass 1 as fallback.[/red]")
        for stage in failure_stages:
            console.print(f"    Attempt {stage['attempt']}: {stage['error_type']}: {stage['error'][:100]}")

        # Return Pass 1 data as fallback (clearly marked degraded)
        fallback = {
            "id": app_record.get("id"),
            "app": app_name,
            "category": app_record.get("category", ""),
            "auth_methods": app_record.get("auth_methods", []),
            "self_serve_status": app_record.get("self_serve_status", ""),
            "api_surface": app_record.get("api_surface", ""),
            "api_breadth": app_record.get("api_breadth", ""),
            "has_mcp": app_record.get("has_mcp", ""),
            "buildability_verdict": app_record.get("buildability_verdict", ""),
            "_recheck_used_pass1_fallback": True,
        }
        return {
            "status": "failed",
            "data": fallback,
            "failure_stages": failure_stages,
            "last_error": last_error,
        }


async def run_verifier(
    pass1_results: list[dict],
    apps_master: list[dict],
    checklist_path: str = "verification/human_checklist.csv",
    field_agreement_path: str = "verification/field_level_agreement.json",
    sample_size: int = 20,
    failed_app_names: Optional[list[str]] = None,  # if set, only re-check these apps
) -> list[dict]:
    """
    Run stratified re-check on 20 apps, generate human checklist CSV.
    Returns list of sampled+compared results.
    """
    console.rule("[bold cyan]Agent 3: Verifier (Re-check Pass)[/bold cyan]")

    random.seed(42)

    if failed_app_names:
        # Targeted re-run: only re-check the specified apps
        sampled = [r for r in pass1_results if r.get("app") in set(failed_app_names)]
        console.print(f"  Targeted re-check for {len(sampled)} previously-failed apps")
    else:
        sampled = _stratified_sample(pass1_results, n=sample_size)
        console.print(f"  Sampled {len(sampled)} apps for verification:")
        for s in sampled:
            console.print(f"    [{s.get('confidence', '?')}] {s['app']} ({s.get('category', '?')})")

    hint_lookup = {a["app"]: a for a in apps_master}

    import os as _os
    OPENAI_API_KEY = _os.environ.get("OPENAI_API_KEY", "")

    def search_tool(query: str) -> str:
        """Search the web using Tavily — instrumented with error details."""
        from tavily import TavilyClient
        TAVILY_API_KEY = _os.environ.get("TAVILY_API_KEY", "")
        if not TAVILY_API_KEY:
            return "ERROR: TAVILY_API_KEY not set"
        client = TavilyClient(api_key=TAVILY_API_KEY)
        for attempt in range(1, 4):
            try:
                result = client.search(
                    query=query,
                    search_depth="basic",
                    max_results=5,
                    include_raw_content=False,
                )
                results_list = result.get("results", [])
                if not results_list:
                    return "No results found (empty Tavily response)"
                snippets = [
                    f"URL: {r['url']}\nTitle: {r.get('title','')}\nSnippet: {r.get('content','')[:400]}"
                    for r in results_list
                ]
                return "\n\n---\n\n".join(snippets)
            except Exception as e:
                if attempt < 3:
                    time.sleep(2 ** attempt)
                else:
                    return f"ERROR [Tavily, attempt {attempt}]: {type(e).__name__}: {str(e)[:300]}"
        return "ERROR: Tavily search failed after 3 attempts"

    def fetch_page_tool(url: str) -> str:
        """Fetch and clean a webpage — instrumented with error details."""
        from agents.researcher import fetch_page
        result = fetch_page(url)
        if result.startswith("ERROR:"):
            console.print(f"    [dim red]fetch_page: {result[:80]}[/dim red]")
        return result

    from agno.agent import Agent
    from agno.models.openai import OpenAIChat

    alt_agent = Agent(
        model=OpenAIChat(id="gpt-4.1-mini", api_key=OPENAI_API_KEY),
        tools=[search_tool, fetch_page_tool],
        instructions=ALTERNATIVE_SYSTEM_PROMPT,
        markdown=False,
        debug_mode=False,
    )

    semaphore = asyncio.Semaphore(3)

    console.print(f"\n  Running re-check on {len(sampled)} apps (alternative query strategy)...")
    tasks = [
        _recheck_single_app(
            s,
            hint_lookup.get(s["app"], {}).get("hint", s["app"]),
            alt_agent,
            semaphore,
        )
        for s in sampled
    ]
    recheck_raw = await asyncio.gather(*tasks)

    recheck_lookup = {r["data"]["app"]: r for r in recheck_raw}

    # ── Build comparisons ──────────────────────────────────────────────────
    comparisons = []
    for p1 in sampled:
        app_name = p1["app"]
        rc_result = recheck_lookup.get(app_name, {"status": "failed", "data": {}})
        rc_status = rc_result["status"]    # ok | failed
        rc_data = rc_result["data"]

        comparison = _compare_fields(p1, rc_data)
        comparisons.append({
            "app": app_name,
            "category": p1.get("category", ""),
            "pass1_confidence": p1.get("confidence", ""),
            "recheck_status": rc_status,
            "comparison": comparison,
            "pass1_data": p1,
            "recheck_data": rc_data,
            "failure_stages": rc_result.get("failure_stages", []),
        })

    # ── Write CSV ──────────────────────────────────────────────────────────
    # If updating existing CSV (targeted re-run), load existing and merge
    existing_rows: dict[tuple, dict] = {}
    if failed_app_names and os.path.exists(checklist_path):
        with open(checklist_path, newline="") as f:
            for row in csv.DictReader(f):
                key = (row["app"], row["field"])
                existing_rows[key] = row

    csv_rows = []
    for comp in comparisons:
        app = comp["app"]
        rc_status = comp["recheck_status"]
        for field in FIELDS_TO_VERIFY:
            field_comp = comp["comparison"].get(field, {})
            key = (app, field)

            # Preserve existing human_verified_correct_answer if present
            existing = existing_rows.get(key, {})
            human_answer = existing.get("human_verified_correct_answer", "")

            # Only flag as disagreement if re-check actually ran OK
            if rc_status == "ok":
                agreement = "yes" if field_comp.get("agree") else "no"
                recheck_answer = field_comp.get("recheck", "")
            else:
                # Failed re-check: not a disagreement, just unknown
                agreement = "recheck_failed"
                recheck_answer = f"FAILED: {comp['failure_stages'][-1]['error'][:80]}" if comp["failure_stages"] else "FAILED"

            csv_rows.append({
                "app": app,
                "category": comp["category"],
                "pass1_confidence": comp["pass1_confidence"],
                "field": field,
                "pass1_answer": field_comp.get("pass1", ""),
                "recheck_answer": recheck_answer,
                "agreement": agreement,
                "recheck_status": rc_status,
                "human_verified_correct_answer": human_answer,
            })

    # Sort: ok rows first (sorted by app+field), then degraded/failed at bottom
    csv_rows.sort(key=lambda r: (
        0 if r["recheck_status"] == "ok" else 1,
        r["app"],
        FIELDS_TO_VERIFY.index(r["field"]) if r["field"] in FIELDS_TO_VERIFY else 99,
    ))

    # If targeted re-run, merge back with existing rows for non-targeted apps
    if failed_app_names and existing_rows:
        targeted_apps = set(failed_app_names)
        kept_existing = [
            row for (app, _), row in existing_rows.items()
            if app not in targeted_apps
        ]
        # Add recheck_status and pass1_confidence to old rows if missing
        for row in kept_existing:
            row.setdefault("recheck_status", "ok")
            row.setdefault("pass1_confidence", "")
        csv_rows.extend(kept_existing)
        csv_rows.sort(key=lambda r: (
            0 if r.get("recheck_status", "ok") == "ok" else 1,
            r["app"],
            FIELDS_TO_VERIFY.index(r["field"]) if r["field"] in FIELDS_TO_VERIFY else 99,
        ))

    os.makedirs(os.path.dirname(checklist_path), exist_ok=True)
    fieldnames = ["app", "category", "pass1_confidence", "field", "pass1_answer",
                  "recheck_answer", "agreement", "recheck_status", "human_verified_correct_answer"]
    with open(checklist_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(csv_rows)

    # ── Fix 3: Field-level agreement stats ────────────────────────────────
    _compute_field_agreement(csv_rows, field_agreement_path)

    # ── Summary ───────────────────────────────────────────────────────────
    ok_apps = sum(1 for c in comparisons if c["recheck_status"] == "ok")
    failed_apps = sum(1 for c in comparisons if c["recheck_status"] == "failed")
    ok_rows = [r for r in csv_rows if r["recheck_status"] == "ok"]
    agree_ok = sum(1 for r in ok_rows if r["agreement"] == "yes")
    total_ok = len(ok_rows)

    console.print(f"\n[bold green]Verification re-check complete![/bold green]")
    console.print(f"  Apps successfully re-checked: {ok_apps}/{len(sampled)}")
    console.print(f"  Apps failed (all 3 attempts): {failed_apps}")
    console.print(f"  Pass1 ↔ Re-check agreement (ok rows only): {round(agree_ok/total_ok*100,1) if total_ok else 0}% ({agree_ok}/{total_ok})")
    console.print(f"  Checklist saved → {checklist_path}")
    console.print(f"  Field-level agreement saved → {field_agreement_path}")

    return comparisons


def _compute_field_agreement(
    csv_rows: list[dict],
    output_path: str,
) -> dict:
    """
    Fix 3: Compute per-field agreement rate, excluding recheck_status != 'ok'.
    Saves to verification/field_level_agreement.json and prints summary.
    """
    ok_rows = [r for r in csv_rows if r.get("recheck_status", "ok") == "ok"]

    by_field: dict[str, dict] = {}
    for field in FIELDS_TO_VERIFY:
        field_rows = [r for r in ok_rows if r["field"] == field]
        total = len(field_rows)
        agree = sum(1 for r in field_rows if r["agreement"] == "yes")
        pct = round(agree / total * 100, 1) if total else 0

        # Collect specific disagreements
        disagree_examples = []
        for r in field_rows:
            if r["agreement"] != "yes":
                disagree_examples.append({
                    "app": r["app"],
                    "pass1": r["pass1_answer"],
                    "recheck": r["recheck_answer"],
                })

        by_field[field] = {
            "total_ok_checked": total,
            "agree": agree,
            "disagree": total - agree,
            "agreement_pct": pct,
            "disagree_examples": disagree_examples[:5],  # cap at 5 for readability
        }

    # Rank by agreement_pct ascending (worst first)
    ranked = sorted(by_field.items(), key=lambda x: x[1]["agreement_pct"])

    # Diagnosis: flag judgment calls vs. likely prompt/schema fix candidates
    diagnosis = {}
    JUDGMENT_FIELDS = {"auth_methods"}  # auth_methods is a list, normalization is the issue
    for field, stats in by_field.items():
        pct = stats["agreement_pct"]
        if pct >= 80:
            diagnosis[field] = "✅ High agreement — likely reliable"
        elif field in JUDGMENT_FIELDS:
            diagnosis[field] = "🔧 Low agreement but likely normalization issue (list ordering/naming variations, not semantic disagreement) — check disagree_examples"
        elif pct < 50:
            diagnosis[field] = "⚠️  Very low agreement — likely a prompt ambiguity or schema interpretation issue; consider tightening the Pass 1 prompt for this field"
        else:
            diagnosis[field] = "🔶 Moderate agreement — some genuine judgment call expected, but worth reviewing disagreements"

    result = {
        "note": "Rows with recheck_status != 'ok' excluded from this calculation",
        "ok_rows_used": len(ok_rows),
        "field_agreement": {
            field: {**stats, "diagnosis": diagnosis[field]}
            for field, stats in by_field.items()
        },
        "ranked_worst_to_best": [
            {"field": f, "agreement_pct": s["agreement_pct"], "diagnosis": diagnosis[f]}
            for f, s in ranked
        ],
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)

    console.rule("[bold cyan]Fix 3: Field-Level Agreement[/bold cyan]")
    console.print(f"  (Using {len(ok_rows)} ok-status rows only)\n")
    console.print("  Field                      Agreement   Diagnosis")
    console.print("  " + "─" * 80)
    for field, stats in ranked:
        bar = "█" * int(stats["agreement_pct"] / 5)
        console.print(f"  {field:30s} {stats['agreement_pct']:5.1f}%  {diagnosis[field]}")

    console.print(f"\n  Saved → {output_path}")
    return result
