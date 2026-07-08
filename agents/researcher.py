"""
Agent 1: Researcher
Searches, fetches, and analyzes API documentation for each app to determine
AI-agent toolkit readiness. Uses Tavily for search and requests+trafilatura
for page fetching.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import re
from typing import Optional

import requests
import trafilatura
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.tools.tavily import TavilyTools

from agents.models import AppResearch, AppInput

console = Console()

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "")

SYSTEM_PROMPT = """You are a precise technical researcher analyzing SaaS and developer tool APIs.

Your task is to research a given app and determine whether it could become an AI-agent toolkit (like Composio does).

You MUST:
1. Use the search tool to find the app's API docs, auth docs, and pricing/partner pages
2. Use the fetch_page tool to read the actual content of relevant pages
3. Return a structured JSON object with EXACTLY these fields (no markdown, no explanation — raw JSON only):

{
  "id": <integer from input>,
  "app": "<app name>",
  "category": "<category from input>",
  "one_liner": "<1 sentence what the app does>",
  "auth_methods": ["<method1>", "<method2>"],
  "self_serve_status": "<one of: self_serve_free | self_serve_trial | gated_paid_plan | gated_approval | gated_partnership | open_source_self_host>",
  "gating_evidence_note": "<brief evidence for self_serve_status>",
  "api_surface": "<one of: rest | graphql | rest_and_graphql | sdk_only | none_public>",
  "api_breadth": "<one of: broad | moderate | narrow>",
  "has_mcp": "<one of: official | community_unofficial | none | unknown>",
  "buildability_verdict": "<one of: ready | ready_with_friction | blocked>",
  "main_blocker": "<'none' if ready, otherwise describe the specific blocker>",
  "evidence_urls": ["<url1>", "<url2>"],
  "confidence": "<one of: high | medium | low>"
}

Definitions:
- auth_methods: list from [oauth2, api_key, jwt, basic_auth, webhook_secret, oauth1, service_account]
- self_serve_status — CRITICAL, read carefully:
  This field describes whether a developer can obtain WORKING API
  CREDENTIALS today for free or on a trial — independent of whether the
  product's OTHER (non-API) features are paywalled. Airtable, for
  example, lets a free-plan user generate a personal access token even
  though other product features are paywalled — that is still
  self_serve_free for this field.
  - self_serve_free: any developer can sign up (free plan or trial that
    does not require payment) and immediately generate a functional API
    key, OAuth app, or other API credential with no human approval step.
    Even if the product's premium FEATURES (storage, seats, advanced
    modules) are paywalled, if the API key/OAuth app itself can be
    generated for free, this is self_serve_free.
  - self_serve_trial: a free trial account (time- or usage-limited) can
    generate working API credentials, but the credentials expire or stop
    working when the trial ends unless the developer converts to a paid
    plan.
  - gated_paid_plan: obtaining API credentials itself requires an active
    paid subscription (not just a trial) — i.e. the API layer, not just
    other product features, is paywalled. Use this ONLY when the
    developer cannot get working API keys at all without paying. Do NOT
    classify as gated_paid_plan just because some premium product
    features require a paid plan; the question is whether the API
    CREDENTIALS themselves are gated behind payment.
  - gated_approval: must apply/request access (human approval process)
  - gated_partnership: enterprise/partner program required
  - open_source_self_host: open source, primarily self-hosted
- api_breadth broad: 20+ distinct resource types/endpoints
- api_breadth moderate: 5-19 resource types
- api_breadth narrow: <5 resource types or very limited scope
- buildability ready: has public API, self-serve access, clear docs
- buildability ready_with_friction: has API but requires paid plan, complex auth, or limited scope
- buildability blocked: no public API, or access requires enterprise approval/partnership

If you cannot find the page (blocked, 404, JS-only), set confidence to "low" and note it in gating_evidence_note.
If you genuinely cannot determine a field, use "unknown" where applicable.

IMPORTANT: Return ONLY the JSON object, nothing else."""


def fetch_page(url: str, timeout: int = 15) -> str:
    """Fetch a webpage and return cleaned text content."""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0; +https://github.com/composio-research)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    try:
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()

        # Try trafilatura first (better at stripping nav/boilerplate)
        text = trafilatura.extract(resp.text, include_comments=False, include_tables=True)
        if text and len(text) > 200:
            return text[:6000]  # Cap at 6k chars to save tokens

        # Fallback: BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:6000]

    except requests.exceptions.Timeout:
        return "ERROR: Request timed out"
    except requests.exceptions.HTTPError as e:
        return f"ERROR: HTTP {e.response.status_code}"
    except requests.exceptions.ConnectionError:
        return "ERROR: Connection failed (blocked_for_research or DNS failure)"
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {str(e)[:200]}"


def build_researcher_agent(query_mode: str = "standard") -> Agent:
    """
    Build the researcher agent. query_mode='standard' or 'alternative'
    (alternative uses different search strategy for verification pass).
    """

    def search_tool(query: str) -> str:
        """Search the web for API documentation and developer info."""
        from tavily import TavilyClient
        client = TavilyClient(api_key=TAVILY_API_KEY)
        try:
            result = client.search(
                query=query,
                search_depth="basic",
                max_results=5,
                include_raw_content=False,
            )
            snippets = []
            for r in result.get("results", []):
                snippets.append(f"URL: {r['url']}\nTitle: {r.get('title','')}\nSnippet: {r.get('content','')[:400]}")
            return "\n\n---\n\n".join(snippets) if snippets else "No results found."
        except Exception as e:
            return f"Search error: {e}"

    def fetch_page_tool(url: str) -> str:
        """Fetch and clean a webpage, stripping nav/boilerplate. Returns text content."""
        return fetch_page(url)

    agent = Agent(
        model=OpenAIChat(id="gpt-4.1-mini", api_key=OPENAI_API_KEY),
        tools=[search_tool, fetch_page_tool],
        instructions=SYSTEM_PROMPT,
        markdown=False,
        debug_mode=False,
    )
    return agent


def extract_json_from_response(text: str) -> Optional[dict]:
    """Extract JSON from agent response, handling markdown code blocks."""
    text = text.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding first { ... } block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return None


async def research_single_app(app: AppInput, agent: Agent, semaphore: asyncio.Semaphore) -> dict:
    """Research a single app with rate-limiting via semaphore."""
    async with semaphore:
        start = time.time()
        hint_url = app.hint.split(" ")[0]  # Strip parenthetical notes
        # Clean URL
        hint_url = re.sub(r'\s.*', '', app.hint).strip()

        try:
            prompt = (
                f"Research this app for AI-agent toolkit buildability:\n"
                f"App: {app.app}\n"
                f"Category: {app.category}\n"
                f"Hint URL / docs: {app.hint}\n\n"
                f"Search for:\n"
                f'1. "{app.app} API documentation developer docs"\n'
                f'2. "{app.app} OAuth API key authentication"\n'
                f'3. "{app.app} API pricing access developer"\n\n'
                f"Fetch the most relevant pages you find. Then return the JSON."
            )

            response = await asyncio.to_thread(agent.run, prompt)
            raw = response.content if hasattr(response, "content") else str(response)
            data = extract_json_from_response(raw)

            if data is None:
                raise ValueError(f"Could not parse JSON from response: {raw[:300]}")

            # Ensure required fields exist
            data.setdefault("id", app.id)
            data.setdefault("app", app.app)
            data.setdefault("category", app.category)
            data.setdefault("error", None)

            elapsed = time.time() - start
            return {"status": "ok", "elapsed": round(elapsed, 1), "data": data}

        except Exception as e:
            elapsed = time.time() - start
            return {
                "status": "error",
                "elapsed": round(elapsed, 1),
                "data": {
                    "id": app.id,
                    "app": app.app,
                    "category": app.category,
                    "one_liner": "RESEARCH_FAILED",
                    "auth_methods": [],
                    "self_serve_status": "gated_approval",
                    "gating_evidence_note": "Research failed",
                    "api_surface": "none_public",
                    "api_breadth": "narrow",
                    "has_mcp": "unknown",
                    "buildability_verdict": "blocked",
                    "main_blocker": f"Research error: {type(e).__name__}: {str(e)[:300]}",
                    "evidence_urls": [],
                    "confidence": "low",
                    "error": f"{type(e).__name__}: {str(e)[:500]}",
                },
            }


async def run_researcher(
    apps: list[dict],
    concurrency: int = 5,
    output_path: str = "data/pass1_results.json",
    query_mode: str = "standard",
) -> list[dict]:
    """Run the Researcher Agent across all apps. Returns list of result dicts."""
    console.rule("[bold cyan]Agent 1: Researcher (Pass 1)[/bold cyan]")

    agent = build_researcher_agent(query_mode=query_mode)
    semaphore = asyncio.Semaphore(concurrency)
    app_inputs = [AppInput(**a) for a in apps]

    results = []
    errors = []
    start_total = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"Researching {len(app_inputs)} apps...", total=len(app_inputs))

        tasks = [research_single_app(app, agent, semaphore) for app in app_inputs]

        for coro in asyncio.as_completed(tasks):
            result = await coro
            results.append(result["data"])

            if result["status"] == "error":
                errors.append({"app": result["data"]["app"], "error": result["data"]["error"]})
                console.print(f"  [red]✗[/red] {result['data']['app']} ({result['elapsed']}s) — {result['data']['error'][:80]}")
            else:
                console.print(f"  [green]✓[/green] {result['data']['app']} ({result['elapsed']}s)")

            progress.advance(task)

    total_time = round(time.time() - start_total, 1)

    # Sort by id before saving, handling None values gracefully
    results.sort(key=lambda x: int(x.get("id") or 9999))

    output = {
        "meta": {
            "total_apps": len(apps),
            "successful": len(apps) - len(errors),
            "errors": len(errors),
            "total_run_time_seconds": total_time,
            "error_log": errors,
        },
        "results": results,
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    console.print(f"\n[bold green]Pass 1 complete![/bold green] {len(apps)-len(errors)}/{len(apps)} apps researched in {total_time}s")
    console.print(f"  Errors: {len(errors)}")
    console.print(f"  Saved → {output_path}\n")

    return results
