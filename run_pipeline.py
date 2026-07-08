"""
run_pipeline.py — Main pipeline orchestrator
Usage: python run_pipeline.py

Runs three agents in sequence, pausing for human verification after Agent 3.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from rich.console import Console
from rich.panel import Panel

console = Console()


def check_env():
    """Check required environment variables."""
    issues = []
    if not os.environ.get("OPENAI_API_KEY"):
        issues.append("OPENAI_API_KEY not set")
    if not os.environ.get("TAVILY_API_KEY"):
        issues.append("TAVILY_API_KEY not set")
    if not os.environ.get("COMPOSIO_API_KEY"):
        console.print("[yellow]⚠  COMPOSIO_API_KEY not set — Composio cross-check will be skipped[/yellow]")
    if issues:
        for issue in issues:
            console.print(f"[red]✗ {issue}[/red]")
        console.print("\n[red]Set the missing env vars and retry.[/red]")
        sys.exit(1)


def load_apps() -> list[dict]:
    path = Path("data/apps_master_list.json")
    if not path.exists():
        console.print("[red]✗ data/apps_master_list.json not found![/red]")
        sys.exit(1)
    with open(path) as f:
        apps = json.load(f)
    console.print(f"[green]✓[/green] Loaded {len(apps)} apps from {path}")
    return apps


async def main():
    console.print(Panel.fit(
        "[bold]AI-Agent Toolkit Readiness Pipeline[/bold]\n"
        "3-agent Agno pipeline · OpenAI GPT-4o · Tavily",
        border_style="bright_blue",
    ))

    check_env()
    apps = load_apps()

    # ─────────────────────────────────────────────────────────
    # STAGE 1: Researcher Agent (Pass 1)
    # ─────────────────────────────────────────────────────────
    stage_start = time.time()

    if Path("data/pass1_results.json").exists():
        console.print("\n[yellow]⚡ pass1_results.json already exists — skipping Agent 1 (delete it to re-run)[/yellow]")
        with open("data/pass1_results.json") as f:
            pass1_data = json.load(f)
        pass1_results = pass1_data["results"]
    else:
        console.print()
        from agents.researcher import run_researcher
        pass1_results = await run_researcher(apps, concurrency=5)

    console.print(f"[dim]Stage 1 elapsed: {round(time.time()-stage_start,1)}s[/dim]\n")

    # ─────────────────────────────────────────────────────────
    # STAGE 2: Composio Cross-Check
    # ─────────────────────────────────────────────────────────
    stage_start = time.time()

    cc_path = Path("data/composio_crosscheck.json")
    skip_cc = False
    if cc_path.exists():
        with open(cc_path) as f:
            cc_meta = json.load(f).get("meta", {})
        # Skip only if we actually found results (not the old all-not_checked run)
        if cc_meta.get("found_in_composio", 0) > 0:
            console.print("[yellow]⚡ composio_crosscheck.json already exists with real data — skipping Agent 2 (delete it to re-run)[/yellow]")
            skip_cc = True

    if skip_cc:
        with open(cc_path) as f:
            composio_results = json.load(f)["results"]
    else:
        from agents.composio_checker import run_composio_crosscheck
        composio_results = run_composio_crosscheck(pass1_results)

    console.print(f"[dim]Stage 2 elapsed: {round(time.time()-stage_start,1)}s[/dim]\n")

    # ─────────────────────────────────────────────────────────
    # STAGE 3: Verifier Agent
    # ─────────────────────────────────────────────────────────
    stage_start = time.time()

    checklist_path = "verification/human_checklist.csv"
    skip_verifier = False
    if Path(checklist_path).exists():
        with open(checklist_path, newline="") as f:
            import csv as _csv
            sample_rows = list(_csv.DictReader(f))
        # Skip only if CSV has new schema (recheck_status column present)
        if sample_rows and "recheck_status" in sample_rows[0]:
            console.print("[yellow]⚡ human_checklist.csv already exists with recheck_status column — skipping Agent 3 (delete it to re-run)[/yellow]")
            skip_verifier = True

    if not skip_verifier:
        from agents.verifier import run_verifier
        await run_verifier(pass1_results, apps, checklist_path=checklist_path)

    console.print(f"[dim]Stage 3 elapsed: {round(time.time()-stage_start,1)}s[/dim]\n")

    # ─────────────────────────────────────────────────────────
    # ⏸  HUMAN PAUSE
    # ─────────────────────────────────────────────────────────
    if not Path("data/final_results.json").exists():
        console.print(Panel(
            "[bold yellow]⏸  HUMAN VERIFICATION REQUIRED[/bold yellow]\n\n"
            "Please open [bold]verification/human_checklist.csv[/bold] and fill in\n"
            "the [bold]human_verified_correct_answer[/bold] column for each row\n"
            "by visiting the real developer docs.\n\n"
            "Rows with [bold red]recheck_status = failed[/bold red] are at the bottom —\n"
            "those are pipeline failures, NOT disagreements. You can leave them blank\n"
            "or verify from scratch if you wish.\n\n"
            "When done, type [bold green]continue[/bold green] and press Enter:",
            border_style="yellow",
        ))

        while True:
            user_input = input(">>> ").strip().lower()
            if user_input == "continue":
                break
            else:
                console.print("[dim]Type 'continue' to proceed...[/dim]")

    # ─────────────────────────────────────────────────────────
    # POST-HUMAN: Accuracy + Final Results
    # ─────────────────────────────────────────────────────────
    stage_start = time.time()

    if Path("data/final_results.json").exists():
        console.print("[yellow]⚡ final_results.json already exists — skipping accuracy computation (delete it to re-run)[/yellow]")
    else:
        from agents.accuracy_computer import load_checklist, compute_accuracy, compute_accuracy_no_human

        checklist_path = "verification/human_checklist.csv"
        checklist_rows = load_checklist(checklist_path)

        # Check if human actually filled anything in
        filled = [r for r in checklist_rows if r.get("human_verified_correct_answer", "").strip()]
        if filled:
            console.rule("[bold cyan]Computing Accuracy[/bold cyan]")
            compute_accuracy(checklist_rows, pass1_results, composio_results)
        else:
            console.print("[yellow]⚠  No human answers found in checklist — using Pass 1 results as final (no accuracy correction)[/yellow]")
            compute_accuracy_no_human(pass1_results, composio_results)

    console.print(f"[dim]Accuracy stage elapsed: {round(time.time()-stage_start,1)}s[/dim]\n")

    # ─────────────────────────────────────────────────────────
    # PATTERN ANALYSIS
    # ─────────────────────────────────────────────────────────
    if Path("data/patterns.json").exists():
        console.print("[yellow]⚡ patterns.json already exists — skipping analysis (delete it to re-run)[/yellow]")
    else:
        from analysis.pattern_analyzer import run_pattern_analysis
        run_pattern_analysis()

    # ─────────────────────────────────────────────────────────
    # HTML GENERATION
    # ─────────────────────────────────────────────────────────
    from analysis.html_builder import build_html
    html_path = build_html()

    # ─────────────────────────────────────────────────────────
    # DONE
    # ─────────────────────────────────────────────────────────
    console.print(Panel.fit(
        f"[bold green]✅ Pipeline Complete![/bold green]\n\n"
        f"  📄 HTML report → [bold]{html_path}[/bold]\n"
        f"  📊 Patterns    → data/patterns.json\n"
        f"  📋 Final data  → data/final_results.json\n"
        f"  🔍 Accuracy    → verification/accuracy_report.json",
        border_style="green",
    ))


if __name__ == "__main__":
    asyncio.run(main())
