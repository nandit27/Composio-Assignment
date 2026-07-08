"""
Agent 2: Composio Cross-Check (v3 API)
Uses the Composio v3 REST API (/api/v3/toolkits) directly — the composio-core
SDK is deprecated and calls 410-dead endpoints. This avoids the SDK entirely.

Distinct status values:
  exists_in_composio: True | False ("not_in_composio_catalog") | "lookup_failed"
"""

from __future__ import annotations

import json
import os
import re
import time
from difflib import SequenceMatcher
from typing import Optional

import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

console = Console()

COMPOSIO_API_KEY = os.environ.get("COMPOSIO_API_KEY", "")
TOOLKITS_URL = "https://backend.composio.dev/api/v3/toolkits"


def _normalize(name: str) -> str:
    """Normalize app name for fuzzy matching."""
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _fetch_catalog() -> tuple[list[dict], Optional[str]]:
    """
    Fetch the full Composio toolkit catalog from the v3 API.
    Returns (catalog_items, error_message). On success error_message is None.
    """
    if not COMPOSIO_API_KEY:
        return [], "COMPOSIO_API_KEY not set"

    all_items: list[dict] = []
    page = 1
    headers = {"x-api-key": COMPOSIO_API_KEY}

    while True:
        try:
            resp = requests.get(
                TOOLKITS_URL,
                headers=headers,
                params={"page": page, "limit": 100},
                timeout=20,
            )
        except requests.exceptions.RequestException as e:
            return [], f"Network error: {e}"

        if not resp.ok:
            return [], f"HTTP {resp.status_code}: {resp.text[:200]}"

        data = resp.json()
        items = data.get("items", [])
        all_items.extend(items)

        total_pages = data.get("totalPages", 1)
        if page >= total_pages or not items:
            break
        page += 1

    return all_items, None


def _find_match(app_name: str, catalog: list[dict]) -> Optional[dict]:
    """Fuzzy-match app name against catalog. Returns best match if score >= 0.70."""
    best_score = 0.0
    best_item = None

    for item in catalog:
        # Match against name and slug
        for field in ("name", "slug"):
            val = str(item.get(field, "")).strip()
            if not val:
                continue
            score = _similarity(app_name, val)
            if score > best_score:
                best_score = score
                best_item = item

    return best_item if best_score >= 0.70 else None


def run_composio_crosscheck(
    pass1_results: list[dict],
    output_path: str = "data/composio_crosscheck.json",
) -> list[dict]:
    """
    Cross-check all 100 apps against the Composio v3 toolkit catalog.
    Returns list of crosscheck result dicts.
    """
    console.rule("[bold cyan]Agent 2: Composio Cross-Check (v3 API)[/bold cyan]")

    # ── Fetch catalog ─────────────────────────────────────────────────────
    if not COMPOSIO_API_KEY:
        console.print("[yellow]⚠  COMPOSIO_API_KEY not set — skipping cross-check[/yellow]")
        return _make_not_checked_results(pass1_results, output_path, reason="api_key_missing")

    console.print("  Fetching Composio v3 toolkit catalog...")
    catalog, err = _fetch_catalog()

    if err:
        console.print(f"[red]  Catalog fetch failed: {err}[/red]")
        return _make_not_checked_results(pass1_results, output_path, reason=f"catalog_fetch_failed: {err}")

    console.print(f"  ✓ Loaded {len(catalog)} toolkits from Composio catalog")
    # Show a sample of names
    sample = [item["name"] for item in catalog[:10]]
    console.print(f"  Sample: {sample}")

    # ── Cross-check each app ──────────────────────────────────────────────
    results: list[dict] = []
    agreement_stats = {"agree": 0, "disagree": 0, "checked": 0}

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Cross-checking apps...", total=len(pass1_results))

        for r in pass1_results:
            app_name = r.get("app", "")
            match = _find_match(app_name, catalog)

            if match:
                # ── Found in Composio ──────────────────────────────────
                auth_schemes = match.get("auth_schemes", [])
                composio_auth = ",".join(s.lower() for s in auth_schemes) if auth_schemes else "unknown"
                meta = match.get("meta", {})
                tool_count = meta.get("tools_count", 0) + meta.get("triggers_count", 0)
                slug = match.get("slug", match.get("name", ""))
                composio_url = f"https://app.composio.dev/apps/{slug}"

                # Auth agreement
                pass1_auths = [a.lower() for a in r.get("auth_methods", [])]
                auth_agrees = None
                if pass1_auths and composio_auth != "unknown":
                    auth_agrees = any(
                        any(ca in pa or pa in ca for pa in pass1_auths)
                        for ca in composio_auth.split(",")
                    )

                agreement_stats["checked"] += 1
                if auth_agrees is True:
                    agreement_stats["agree"] += 1
                    auth_agreement = "agree"
                elif auth_agrees is False:
                    agreement_stats["disagree"] += 1
                    auth_agreement = "disagree"
                else:
                    auth_agreement = "unknown"

                results.append({
                    "app": app_name,
                    "category": r.get("category", ""),
                    "exists_in_composio": True,
                    "composio_name": match.get("name", ""),
                    "composio_auth_type": composio_auth,
                    "composio_tool_count": tool_count,
                    "composio_url": composio_url,
                    "auth_agreement": auth_agreement,
                    "pass1_auth_methods": r.get("auth_methods", []),
                })
            else:
                # ── NOT found in Composio catalog ─────────────────────
                results.append({
                    "app": app_name,
                    "category": r.get("category", ""),
                    "exists_in_composio": "not_in_composio_catalog",
                    "composio_name": None,
                    "composio_auth_type": None,
                    "composio_tool_count": None,
                    "composio_url": None,
                    "auth_agreement": "n/a",
                    "pass1_auth_methods": r.get("auth_methods", []),
                })

            progress.advance(task)

    # ── Summary ───────────────────────────────────────────────────────────
    found = sum(1 for r in results if r["exists_in_composio"] is True)
    not_found = sum(1 for r in results if r["exists_in_composio"] == "not_in_composio_catalog")
    failed = sum(1 for r in results if r["exists_in_composio"] == "lookup_failed")

    console.print(f"\n[bold green]Cross-check complete![/bold green]")
    console.print(f"  ✅ In Composio catalog:     {found}")
    console.print(f"  ❌ Not in catalog:          {not_found}")
    console.print(f"  ⚠  Lookup failed:           {failed}")
    if agreement_stats["checked"] > 0:
        pct = round(agreement_stats["agree"] / agreement_stats["checked"] * 100, 1)
        console.print(f"  Auth agreement: {pct}% ({agreement_stats['agree']}/{agreement_stats['checked']})")

    _save(results, output_path, found, not_found, failed)
    return results


def _make_not_checked_results(
    pass1_results: list[dict],
    output_path: str,
    reason: str = "not_checked",
) -> list[dict]:
    results = [
        {
            "app": r.get("app", ""),
            "category": r.get("category", ""),
            "exists_in_composio": "lookup_failed",
            "composio_name": None,
            "composio_auth_type": None,
            "composio_tool_count": None,
            "composio_url": None,
            "auth_agreement": "n/a",
            "pass1_auth_methods": r.get("auth_methods", []),
            "lookup_failure_reason": reason,
        }
        for r in pass1_results
    ]
    _save(results, output_path, 0, 0, len(results))
    return results


def _save(results: list[dict], output_path: str, found: int, not_found: int, failed: int):
    total = len(results)
    output = {
        "meta": {
            "total_apps": total,
            "found_in_composio": found,
            "not_in_composio_catalog": not_found,
            "lookup_failed": failed,
            "composio_coverage_pct": round(found / total * 100, 1) if total else 0,
        },
        "results": results,
    }
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    console.print(f"  Saved → {output_path}\n")
