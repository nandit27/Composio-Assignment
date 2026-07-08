"""
HTML Case Study Generator
Builds the self-contained output/case_study.html from final_results.json,
patterns.json, composio_crosscheck.json, and accuracy_report.json.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from rich.console import Console

console = Console()


def _load_json(path: str, default: Any = None) -> Any:
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


from typing import Any


def build_html(
    final_results_path: str = "data/final_results.json",
    patterns_path: str = "data/patterns.json",
    composio_crosscheck_path: str = "data/composio_crosscheck.json",
    accuracy_report_path: str = "verification/accuracy_report.json",
    output_path: str = "output/case_study.html",
) -> str:
    console.rule("[bold cyan]Generating HTML Case Study[/bold cyan]")

    final_data = _load_json(final_results_path, {"results": []})
    patterns = _load_json(patterns_path, {})
    cc_data = _load_json(composio_crosscheck_path, {"results": [], "meta": {}})
    accuracy = _load_json(accuracy_report_path, {"summary": {}, "field_level_accuracy": {}})

    results = final_data.get("results", [])
    insights = patterns.get("headline_insights", [])
    verdict_dist = patterns.get("buildability_verdicts", {}).get("overall", {})
    ss_overall = patterns.get("self_serve_vs_gated", {}).get("overall", {})
    auth_overall = patterns.get("auth_method_distribution", {}).get("overall", {})
    mcp_dist = patterns.get("mcp_distribution", {})
    composio_cov = patterns.get("composio_coverage", {})
    cat_stats = patterns.get("category_stats", {})
    category_outliers = patterns.get("category_outliers", {})
    blockers = patterns.get("blockers_ranked", [])
    acc_summary = accuracy.get("summary", {})
    field_acc = accuracy.get("field_level_accuracy", {})
    status_dist = patterns.get("self_serve_vs_gated", {}).get("status_distribution", {})

    # Build table rows
    VERDICT_COLOR = {"ready": "#22c55e", "ready_with_friction": "#f59e0b", "blocked": "#ef4444"}
    SS_COLOR = {
        "self_serve_free": "#22c55e", "self_serve_trial": "#84cc16",
        "open_source_self_host": "#06b6d4",
        "gated_paid_plan": "#f59e0b", "gated_approval": "#f97316",
        "gated_partnership": "#ef4444",
    }

    # Group by category for table rendering
    by_cat: dict[str, list] = {}
    for r in results:
        cat = r.get("category", "Unknown")
        by_cat.setdefault(cat, []).append(r)

    table_rows_html = ""
    for cat in sorted(by_cat.keys()):
        apps = by_cat[cat]
        table_rows_html += f"""
            <tr class="cat-header">
              <td colspan="8"><span class="cat-badge">{cat}</span></td>
            </tr>"""
        for r in apps:
            app = r.get("app", "")
            verdict = r.get("buildability_verdict", "")
            verdict_color = VERDICT_COLOR.get(verdict, "#6b7280")
            ss = r.get("self_serve_status", "")
            ss_color = SS_COLOR.get(ss, "#6b7280")
            auth = ", ".join(r.get("auth_methods", [])) if isinstance(r.get("auth_methods"), list) else str(r.get("auth_methods", ""))
            api_surface = r.get("api_surface", "")
            has_mcp = r.get("has_mcp", "unknown")
            mcp_icon = {"official": "✅", "community_unofficial": "🔶", "none": "❌", "unknown": "❓"}.get(has_mcp, "❓")
            evidence = r.get("evidence_urls", [])
            ev_url = evidence[0] if evidence else ""
            ev_link = f'<a href="{ev_url}" target="_blank" class="ev-link" title="{ev_url}">docs ↗</a>' if ev_url else "—"
            in_composio = r.get("exists_in_composio", "not_checked")
            comp_icon = "✅" if in_composio is True else ("❌" if in_composio is False else "—")
            blocker = r.get("main_blocker", "none")
            blocker_short = blocker[:50] + "…" if len(str(blocker)) > 50 else blocker
            conf = r.get("confidence", "")
            conf_class = {"high": "conf-high", "medium": "conf-med", "low": "conf-low"}.get(conf, "")

            table_rows_html += f"""
            <tr class="app-row" data-category="{cat}" data-verdict="{verdict}" data-ss="{ss}">
              <td class="app-name">{app}</td>
              <td><span style="color:{ss_color};font-weight:600;">{ss.replace('_',' ')}</span></td>
              <td><span class="verdict-badge" style="background:{verdict_color}20;color:{verdict_color};border:1px solid {verdict_color}40;">{verdict.replace('_',' ')}</span></td>
              <td class="auth-cell">{auth}</td>
              <td>{api_surface.replace('_', '+')}</td>
              <td title="{has_mcp}">{mcp_icon}</td>
              <td>{comp_icon}</td>
              <td>{ev_link}</td>
            </tr>"""

    # Build insight cards
    insight_icons = ["📊", "🔑", "🔐", "🎯", "🤖", "🔗"]
    insight_cards = ""
    for i, insight in enumerate(insights):
        icon = insight_icons[i % len(insight_icons)]
        insight_cards += f"""
            <div class="insight-card" style="--delay:{i*0.1}s">
              <div class="insight-icon">{icon}</div>
              <p>{insight}</p>
            </div>"""

    # Build field accuracy table
    acc_table_rows = ""
    if field_acc:
        for field, vals in field_acc.items():
            acc = vals.get("pass1_accuracy_pct", "?")
            total = vals.get("total_checked", 0)
            correct = vals.get("pass1_correct", 0)
            sys_errs = vals.get("systematic_errors", {})
            sys_txt = "; ".join(f"'{k}'→'{v}'" for k, v in sys_errs.items()) if sys_errs else "none"
            color = "#22c55e" if isinstance(acc, (int, float)) and acc >= 80 else ("#f59e0b" if isinstance(acc, (int, float)) and acc >= 60 else "#ef4444")
            acc_table_rows += f"""
                <tr>
                  <td style="font-weight:600">{field}</td>
                  <td>{correct}/{total}</td>
                  <td style="color:{color};font-weight:700">{acc}%</td>
                  <td style="font-size:0.8em;opacity:0.7">{sys_txt}</td>
                </tr>"""
    else:
        pass1_acc = acc_summary.get("pass1_overall_accuracy_pct", "not computed")
        acc_table_rows = f"""
            <tr>
              <td colspan="4" style="text-align:center;opacity:0.6">
                {pass1_acc if isinstance(pass1_acc, str) else f'Overall: {pass1_acc}%'}
              </td>
            </tr>"""

    # Blocker bars
    max_blocker = max((b["count"] for b in blockers), default=1)
    blocker_bars = ""
    for b in blockers:
        pct = round(b["count"] / max_blocker * 100)
        blocker_bars += f"""
            <div class="blocker-row">
              <div class="blocker-label">{b['blocker']}</div>
              <div class="blocker-bar-wrap">
                <div class="blocker-bar" style="width:{pct}%"></div>
                <span class="blocker-count">{b['count']}</span>
              </div>
            </div>"""

    # Category heatmap rows
    cat_heatmap = ""
    for cat in sorted(cat_stats.keys()):
        s = cat_stats[cat]
        ss_pct = s.get("self_serve_pct", 0)
        g_pct = s.get("gated_pct", 0)
        r_pct = s.get("ready_pct", 0)
        cat_heatmap += f"""
          <tr>
            <td style="font-weight:600;white-space:nowrap">{cat}</td>
            <td>
              <div class="mini-bar-wrap">
                <div class="mini-bar green" style="width:{ss_pct}%"></div>
              </div>
              <span class="pct-label">{ss_pct}%</span>
            </td>
            <td>
              <div class="mini-bar-wrap">
                <div class="mini-bar red" style="width:{g_pct}%"></div>
              </div>
              <span class="pct-label">{g_pct}%</span>
            </td>
            <td>
              <div class="mini-bar-wrap">
                <div class="mini-bar blue" style="width:{r_pct}%"></div>
              </div>
              <span class="pct-label">{r_pct}%</span>
            </td>
          </tr>"""

    overall_acc = acc_summary.get("pass1_overall_accuracy_pct", "N/A")
    corrections = acc_summary.get("systematic_corrections_applied_to_full_dataset", 0)
    sample_size = acc_summary.get("total_apps_in_sample", 20)
    composio_found = composio_cov.get("found_in_composio", 0)
    composio_pct = composio_cov.get("coverage_pct", 0)

    ready_n = verdict_dist.get("ready", 0)
    friction_n = verdict_dist.get("ready_with_friction", 0)
    blocked_n = verdict_dist.get("blocked", 0)
    ss_n = ss_overall.get("self_serve", 0)
    gated_n = ss_overall.get("gated", 0)

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI-Agent Toolkit Readiness: 100 SaaS Apps — Composio Research</title>
  <meta name="description" content="A verified, agentic research study of 100 SaaS and developer tools to determine which can become AI-agent toolkits today, powered by a 3-agent pipeline.">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #0a0a0f;
      --bg2: #111118;
      --bg3: #1a1a24;
      --border: #2a2a3a;
      --text: #e8e8f0;
      --text2: #9999bb;
      --accent: #6c63ff;
      --accent2: #00d4aa;
      --accent3: #ff6b6b;
      --ready: #22c55e;
      --friction: #f59e0b;
      --blocked: #ef4444;
      --card-bg: rgba(255,255,255,0.03);
      --card-border: rgba(255,255,255,0.07);
    }}

    * {{ margin: 0; padding: 0; box-sizing: border-box; }}

    html {{ scroll-behavior: smooth; }}

    body {{
      font-family: 'Inter', sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.6;
      overflow-x: hidden;
    }}

    /* ── HERO ─────────────────────────────────────── */
    .hero {{
      position: relative;
      padding: 80px 40px 60px;
      text-align: center;
      overflow: hidden;
    }}
    .hero::before {{
      content: '';
      position: absolute;
      inset: 0;
      background: radial-gradient(ellipse 80% 60% at 50% 0%, rgba(108,99,255,0.18) 0%, transparent 70%);
      pointer-events: none;
    }}
    .hero-badge {{
      display: inline-block;
      background: rgba(108,99,255,0.15);
      border: 1px solid rgba(108,99,255,0.35);
      color: #a78bfa;
      font-size: 0.78rem;
      font-weight: 600;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      padding: 6px 16px;
      border-radius: 50px;
      margin-bottom: 24px;
    }}
    .hero h1 {{
      font-size: clamp(2rem, 5vw, 3.5rem);
      font-weight: 800;
      line-height: 1.1;
      background: linear-gradient(135deg, #fff 0%, #a78bfa 50%, #00d4aa 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      margin-bottom: 20px;
    }}
    .hero p {{
      font-size: 1.1rem;
      color: var(--text2);
      max-width: 680px;
      margin: 0 auto 32px;
    }}
    .hero-stats {{
      display: flex;
      gap: 24px;
      justify-content: center;
      flex-wrap: wrap;
    }}
    .hero-stat {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 16px 28px;
      backdrop-filter: blur(10px);
      transition: transform 0.2s, border-color 0.2s;
    }}
    .hero-stat:hover {{ transform: translateY(-3px); border-color: rgba(108,99,255,0.4); }}
    .hero-stat .big {{ font-size: 2rem; font-weight: 800; color: var(--accent); }}
    .hero-stat .label {{ font-size: 0.78rem; color: var(--text2); text-transform: uppercase; letter-spacing: 0.08em; }}

    /* ── NAV ──────────────────────────────────────── */
    nav {{
      position: sticky;
      top: 0;
      z-index: 100;
      background: rgba(10,10,15,0.85);
      backdrop-filter: blur(20px);
      border-bottom: 1px solid var(--border);
      padding: 0 40px;
      display: flex;
      gap: 0;
      overflow-x: auto;
    }}
    nav a {{
      color: var(--text2);
      text-decoration: none;
      font-size: 0.85rem;
      font-weight: 500;
      padding: 14px 20px;
      border-bottom: 2px solid transparent;
      white-space: nowrap;
      transition: color 0.2s, border-color 0.2s;
    }}
    nav a:hover {{ color: var(--text); border-color: var(--accent); }}

    /* ── SECTIONS ─────────────────────────────────── */
    section {{
      max-width: 1400px;
      margin: 0 auto;
      padding: 60px 40px;
    }}
    h2 {{
      font-size: 1.6rem;
      font-weight: 700;
      margin-bottom: 8px;
      display: flex;
      align-items: center;
      gap: 10px;
    }}
    h2 .num {{
      background: linear-gradient(135deg, var(--accent), var(--accent2));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      font-size: 1rem;
      font-weight: 600;
    }}
    .section-sub {{
      color: var(--text2);
      margin-bottom: 32px;
      font-size: 0.95rem;
    }}
    hr.divider {{
      border: none;
      border-top: 1px solid var(--border);
      margin: 0;
    }}

    /* ── INSIGHTS GRID ────────────────────────────── */
    .insights-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 16px;
    }}
    .insight-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 24px;
      animation: fadeUp 0.6s ease both;
      animation-delay: var(--delay);
      transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
    }}
    .insight-card:hover {{
      transform: translateY(-4px);
      border-color: rgba(108,99,255,0.35);
      box-shadow: 0 12px 40px rgba(108,99,255,0.12);
    }}
    .insight-icon {{ font-size: 1.8rem; margin-bottom: 12px; }}
    .insight-card p {{ font-size: 0.93rem; color: var(--text2); line-height: 1.65; }}
    @keyframes fadeUp {{
      from {{ opacity:0; transform:translateY(20px); }}
      to {{ opacity:1; transform:translateY(0); }}
    }}

    /* ── FILTERS ──────────────────────────────────── */
    .filter-bar {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-bottom: 20px;
      align-items: center;
    }}
    .filter-bar label {{ font-size: 0.82rem; color: var(--text2); }}
    select, input[type=text] {{
      background: var(--bg3);
      border: 1px solid var(--border);
      color: var(--text);
      padding: 6px 12px;
      border-radius: 8px;
      font-size: 0.83rem;
      font-family: inherit;
      transition: border-color 0.2s;
    }}
    select:focus, input[type=text]:focus {{
      outline: none;
      border-color: var(--accent);
    }}

    /* ── TABLE ────────────────────────────────────── */
    .table-wrap {{
      overflow-x: auto;
      border-radius: 12px;
      border: 1px solid var(--border);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.82rem;
    }}
    thead th {{
      background: var(--bg3);
      padding: 12px 14px;
      text-align: left;
      font-weight: 600;
      color: var(--text2);
      text-transform: uppercase;
      font-size: 0.72rem;
      letter-spacing: 0.07em;
      border-bottom: 1px solid var(--border);
      cursor: pointer;
      user-select: none;
      white-space: nowrap;
    }}
    thead th:hover {{ color: var(--text); }}
    thead th.sorted-asc::after {{ content: ' ↑'; color: var(--accent); }}
    thead th.sorted-desc::after {{ content: ' ↓'; color: var(--accent); }}
    tbody tr {{ border-bottom: 1px solid rgba(255,255,255,0.04); transition: background 0.15s; }}
    tbody tr:hover {{ background: rgba(108,99,255,0.06); }}
    tbody tr.cat-header {{ background: var(--bg3); }}
    td {{ padding: 10px 14px; vertical-align: middle; }}
    td.app-name {{ font-weight: 600; white-space: nowrap; }}
    td.auth-cell {{ font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; color: var(--text2); }}
    .verdict-badge {{
      display: inline-block;
      padding: 3px 10px;
      border-radius: 50px;
      font-size: 0.73rem;
      font-weight: 600;
      white-space: nowrap;
    }}
    .cat-badge {{
      display: inline-block;
      padding: 4px 12px;
      background: rgba(108,99,255,0.15);
      border: 1px solid rgba(108,99,255,0.25);
      border-radius: 6px;
      font-size: 0.78rem;
      font-weight: 700;
      color: #a78bfa;
      letter-spacing: 0.05em;
    }}
    .ev-link {{
      color: var(--accent2);
      text-decoration: none;
      font-size: 0.78rem;
      font-weight: 500;
    }}
    .ev-link:hover {{ text-decoration: underline; }}

    /* ── PIPELINE DIAGRAM ─────────────────────────── */
    .pipeline {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 0;
      position: relative;
    }}
    .pipeline-step {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 0;
      padding: 28px 24px;
      position: relative;
      transition: border-color 0.2s;
    }}
    .pipeline-step:first-child {{ border-radius: 16px 0 0 16px; }}
    .pipeline-step:last-child {{ border-radius: 0 16px 16px 0; }}
    .pipeline-step + .pipeline-step {{ border-left: none; }}
    .pipeline-step:hover {{ border-color: rgba(108,99,255,0.4); z-index: 1; }}
    .step-num {{
      font-size: 2.5rem;
      font-weight: 800;
      background: linear-gradient(135deg, var(--accent), var(--accent2));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      background-clip: text;
      line-height: 1;
      margin-bottom: 10px;
    }}
    .step-title {{ font-size: 1rem; font-weight: 700; margin-bottom: 8px; }}
    .step-desc {{ font-size: 0.82rem; color: var(--text2); line-height: 1.6; }}
    .step-tools {{
      margin-top: 12px;
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .step-tool {{
      background: rgba(108,99,255,0.12);
      border: 1px solid rgba(108,99,255,0.2);
      color: #c4b5fd;
      font-size: 0.7rem;
      padding: 3px 10px;
      border-radius: 50px;
      font-family: 'JetBrains Mono', monospace;
    }}
    .human-step {{
      margin-top: 32px;
      background: rgba(245,158,11,0.07);
      border: 1px solid rgba(245,158,11,0.25);
      border-radius: 14px;
      padding: 20px 24px;
      display: flex;
      align-items: flex-start;
      gap: 16px;
    }}
    .human-icon {{ font-size: 2rem; flex-shrink: 0; }}
    .human-desc h3 {{ font-size: 1rem; font-weight: 700; color: #fcd34d; margin-bottom: 6px; }}
    .human-desc p {{ font-size: 0.85rem; color: var(--text2); }}

    /* ── ACCURACY SECTION ─────────────────────────── */
    .acc-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 20px;
    }}
    @media (max-width: 768px) {{ .acc-grid {{ grid-template-columns: 1fr; }} }}
    .acc-card {{
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 24px;
    }}
    .acc-card h3 {{ font-size: 0.9rem; font-weight: 700; color: var(--text2); text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 16px; }}
    .acc-card table {{ font-size: 0.82rem; }}
    .acc-card td {{ padding: 8px 10px; border-bottom: 1px solid rgba(255,255,255,0.05); }}
    .conf-high {{ color: var(--ready); }}
    .conf-med {{ color: var(--friction); }}
    .conf-low {{ color: var(--blocked); }}

    /* ── MINI BARS ─────────────────────────────────── */
    .mini-bar-wrap {{
      display: inline-block;
      width: 80px;
      height: 6px;
      background: rgba(255,255,255,0.06);
      border-radius: 3px;
      margin-right: 6px;
      vertical-align: middle;
    }}
    .mini-bar {{
      height: 100%;
      border-radius: 3px;
      transition: width 1s ease;
    }}
    .mini-bar.green {{ background: var(--ready); }}
    .mini-bar.red {{ background: var(--blocked); }}
    .mini-bar.blue {{ background: var(--accent); }}
    .pct-label {{ font-size: 0.78rem; color: var(--text2); }}

    /* ── BLOCKER BARS ─────────────────────────────── */
    .blocker-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }}
    .blocker-label {{ font-size: 0.82rem; color: var(--text2); width: 260px; flex-shrink: 0; }}
    .blocker-bar-wrap {{ flex: 1; display: flex; align-items: center; gap: 8px; }}
    .blocker-bar {{ height: 20px; background: linear-gradient(90deg, var(--accent), var(--accent2)); border-radius: 4px; min-width: 4px; transition: width 1s ease; }}
    .blocker-count {{ font-size: 0.82rem; font-weight: 600; color: var(--text); }}

    /* ── FOOTER ───────────────────────────────────── */
    footer {{
      text-align: center;
      padding: 40px;
      color: var(--text2);
      font-size: 0.83rem;
      border-top: 1px solid var(--border);
    }}
    footer a {{ color: var(--accent2); text-decoration: none; }}
    footer a:hover {{ text-decoration: underline; }}

    /* ── SUMMARY CHIPS ─────────────────────────────── */
    .chips {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 28px; }}
    .chip {{
      padding: 8px 18px;
      border-radius: 50px;
      font-size: 0.82rem;
      font-weight: 600;
      border: 1px solid;
    }}
    .chip.green {{ background: rgba(34,197,94,0.1); border-color: rgba(34,197,94,0.3); color: #4ade80; }}
    .chip.amber {{ background: rgba(245,158,11,0.1); border-color: rgba(245,158,11,0.3); color: #fcd34d; }}
    .chip.red {{ background: rgba(239,68,68,0.1); border-color: rgba(239,68,68,0.3); color: #f87171; }}
    .chip.purple {{ background: rgba(108,99,255,0.1); border-color: rgba(108,99,255,0.3); color: #a78bfa; }}

    /* ── SCROLLBAR ─────────────────────────────────── */
    ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
    ::-webkit-scrollbar-track {{ background: var(--bg); }}
    ::-webkit-scrollbar-thumb {{ background: var(--border); border-radius: 3px; }}
    ::-webkit-scrollbar-thumb:hover {{ background: var(--accent); }}

    .hidden {{ display: none !important; }}
  </style>
</head>
<body>

<!-- ── HERO ─────────────────────────────────────────────── -->
<div class="hero">
  <div class="hero-badge">🔬 Agentic Research Study · {generated_at}</div>
  <h1>AI-Agent Toolkit Readiness<br>100 SaaS Apps Analyzed</h1>
  <p>A 3-agent pipeline using OpenAI GPT-4o + Tavily research researched, cross-checked, and verified whether each app can become a Composio-style AI-agent connector <em>today</em>.</p>
  <div class="hero-stats">
    <div class="hero-stat">
      <div class="big">{ready_n + friction_n}</div>
      <div class="label">Have Usable APIs</div>
    </div>
    <div class="hero-stat">
      <div class="big" style="color:var(--accent2)">{ss_n}</div>
      <div class="label">Self-Serve Access</div>
    </div>
    <div class="hero-stat">
      <div class="big" style="color:var(--friction)">{gated_n}</div>
      <div class="label">Gated / Blocked</div>
    </div>
    <div class="hero-stat">
      <div class="big" style="color:#a78bfa">{composio_found}</div>
      <div class="label">Already in Composio</div>
    </div>
  </div>
</div>

<!-- ── NAV ──────────────────────────────────────────────── -->
<nav>
  <a href="#insights">💡 Insights</a>
  <a href="#matrix">📊 App Matrix</a>
  <a href="#pipeline">⚙️ Pipeline</a>
  <a href="#verification">✅ Verification</a>
  <a href="#repo">📁 Repo</a>
</nav>

<hr class="divider">

<!-- ── SECTION 1: INSIGHTS ──────────────────────────────── -->
<section id="insights">
  <h2><span class="num">01</span> Headline Patterns</h2>
  <p class="section-sub">Six key findings from analyzing 100 real-world SaaS and developer tool apps for AI-agent toolkit buildability.</p>

  <div class="chips">
    <span class="chip green">✅ {ready_n} Ready</span>
    <span class="chip amber">🔶 {friction_n} Ready w/ Friction</span>
    <span class="chip red">❌ {blocked_n} Blocked</span>
    <span class="chip purple">🏪 {composio_found} in Composio ({composio_pct}%)</span>
  </div>

  <div class="insights-grid">
    {insight_cards}
  </div>

  <!-- Category breakdown table -->
  <h3 style="margin-top:40px;margin-bottom:16px;font-size:1rem;color:var(--text2);text-transform:uppercase;letter-spacing:0.07em;">Self-Serve &amp; Buildability by Category</h3>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Category</th>
          <th>Self-Serve %</th>
          <th>Gated %</th>
          <th>Ready %</th>
        </tr>
      </thead>
      <tbody>
        {cat_heatmap}
      </tbody>
    </table>
  </div>

  <!-- Blocker breakdown -->
  <h3 style="margin-top:40px;margin-bottom:20px;font-size:1rem;color:var(--text2);text-transform:uppercase;letter-spacing:0.07em;">Most Common Blockers</h3>
  <div id="blockers">
    {blocker_bars}
  </div>
</section>

<hr class="divider">

<!-- ── SECTION 2: APP MATRIX ────────────────────────────── -->
<section id="matrix">
  <h2><span class="num">02</span> App Matrix — All 100 Apps</h2>
  <p class="section-sub">Full dataset. Filter by category, verdict, or self-serve status. Click column headers to sort.</p>

  <div class="filter-bar">
    <label>Category:</label>
    <select id="filter-cat" onchange="applyFilters()">
      <option value="">All</option>
      {chr(10).join(f'<option value="{c}">{c}</option>' for c in sorted(by_cat.keys()))}
    </select>
    <label>Verdict:</label>
    <select id="filter-verdict" onchange="applyFilters()">
      <option value="">All</option>
      <option value="ready">Ready</option>
      <option value="ready_with_friction">Ready w/ Friction</option>
      <option value="blocked">Blocked</option>
    </select>
    <label>Access:</label>
    <select id="filter-ss" onchange="applyFilters()">
      <option value="">All</option>
      <option value="self_serve_free">Self-Serve Free</option>
      <option value="self_serve_trial">Self-Serve Trial</option>
      <option value="open_source_self_host">Open Source</option>
      <option value="gated_paid_plan">Gated: Paid Plan</option>
      <option value="gated_approval">Gated: Approval</option>
      <option value="gated_partnership">Gated: Partnership</option>
    </select>
    <label>Search:</label>
    <input type="text" id="filter-search" placeholder="App name…" oninput="applyFilters()">
  </div>

  <div class="table-wrap">
    <table id="app-table">
      <thead>
        <tr>
          <th onclick="sortTable(0)">App</th>
          <th onclick="sortTable(1)">Self-Serve Status</th>
          <th onclick="sortTable(2)">Verdict</th>
          <th onclick="sortTable(3)">Auth</th>
          <th onclick="sortTable(4)">API</th>
          <th onclick="sortTable(5)">MCP</th>
          <th onclick="sortTable(6)">Composio</th>
          <th>Evidence</th>
        </tr>
      </thead>
      <tbody id="table-body">
        {table_rows_html}
      </tbody>
    </table>
  </div>
  <p style="margin-top:12px;font-size:0.78rem;color:var(--text2);" id="row-count"></p>
</section>

<hr class="divider">

<!-- ── SECTION 3: PIPELINE ───────────────────────────────── -->
<section id="pipeline">
  <h2><span class="num">03</span> Pipeline Architecture</h2>
  <p class="section-sub">Three specialized agents in sequence, with one mandatory human verification step.</p>

  <div class="pipeline">
    <div class="pipeline-step">
      <div class="step-num">01</div>
      <div class="step-title">🔍 Researcher Agent</div>
      <div class="step-desc">
        Searches the web and fetches developer docs for each of the 100 apps. For each app it produces a structured 16-field record covering auth methods, API surface, MCP status, and a buildability verdict with evidence URLs.
      </div>
      <div class="step-tools">
        <span class="step-tool">Agno</span>
        <span class="step-tool">GPT-4o</span>
        <span class="step-tool">Tavily Search</span>
        <span class="step-tool">fetch_page (trafilatura)</span>
      </div>
    </div>
    <div class="pipeline-step">
      <div class="step-num">02</div>
      <div class="step-title">🔗 Composio Cross-Check</div>
      <div class="step-desc">
        Uses the Composio Python SDK to check whether each app already exists as a toolkit in Composio's catalog. Computes auth-method agreement/disagreement vs. the Researcher's findings as an automated sanity check.
      </div>
      <div class="step-tools">
        <span class="step-tool">composio-core SDK</span>
        <span class="step-tool">Fuzzy name match</span>
      </div>
    </div>
    <div class="pipeline-step">
      <div class="step-num">03</div>
      <div class="step-title">✅ Verifier Agent</div>
      <div class="step-desc">
        Stratified random re-research of 20 apps (≥2 per category, weighted toward low-confidence results) using a <em>different</em> query strategy. Flags every field where Pass 1 and the re-check disagree.
      </div>
      <div class="step-tools">
        <span class="step-tool">GPT-4o</span>
        <span class="step-tool">Alt search queries</span>
        <span class="step-tool">site:github.com</span>
      </div>
    </div>
  </div>

  <div class="human-step">
    <div class="human-icon">🧑‍💻</div>
    <div class="human-desc">
      <h3>Human-in-the-Loop Verification (Required)</h3>
      <p>After the Verifier Agent generates <code>verification/human_checklist.csv</code>, the pipeline pauses and requires a human to open the real developer docs for each sampled app and fill in the correct answers. Only after explicit confirmation does the pipeline resume to compute field-level accuracy, apply systematic corrections, and generate this report.</p>
    </div>
  </div>
</section>

<hr class="divider">

<!-- ── SECTION 4: VERIFICATION ──────────────────────────── -->
<section id="verification">
  <h2><span class="num">04</span> Verification &amp; Accuracy</h2>
  <p class="section-sub">Pass 1 vs. human-verified accuracy, by field. Includes examples of what the agent got wrong and why.</p>

  <div class="acc-grid">
    <div class="acc-card">
      <h3>Pass 1 Field-Level Accuracy</h3>
      <table>
        <thead>
          <tr>
            <th style="padding:8px 10px;">Field</th>
            <th style="padding:8px 10px;">Correct</th>
            <th style="padding:8px 10px;">Accuracy</th>
            <th style="padding:8px 10px;">Systematic Errors</th>
          </tr>
        </thead>
        <tbody>
          {acc_table_rows}
        </tbody>
      </table>
    </div>
    <div class="acc-card">
      <h3>Summary</h3>
      <table>
        <tbody>
          <tr><td>Apps in sample</td><td style="font-weight:700">{sample_size}</td></tr>
          <tr><td>Pass 1 overall accuracy</td><td style="font-weight:700;color:var(--accent2)">{overall_acc}{'%' if isinstance(overall_acc, (int, float)) else ''}</td></tr>
          <tr><td>Systematic corrections applied</td><td style="font-weight:700">{corrections}</td></tr>
          <tr><td style="padding-top:16px;color:var(--text2);font-size:0.82em" colspan="2">
            Systematic errors are wrong→right patterns occurring ≥2 times in the sample, applied across all 100 records.
          </td></tr>
        </tbody>
      </table>

      <h3 style="margin-top:24px;">Known Agent Failure Modes</h3>
      <ul style="font-size:0.83rem;color:var(--text2);padding-left:1.2em;line-height:1.9">
        <li>JS-rendered docs pages returned blank content (logged as blocked_for_research)</li>
        <li>Marketing pages confused with API docs — inflated "self_serve_free" classifications</li>
        <li>MCP status often "unknown" for newer/niche apps with little public documentation</li>
        <li>Paywalled API portals caused under-counting of gated_partnership apps</li>
        <li>Fuzzy name matching in Composio cross-check may miss abbreviated app names</li>
      </ul>
    </div>
  </div>
</section>

<hr class="divider">

<!-- ── SECTION 5: REPO ───────────────────────────────────── -->
<section id="repo">
  <h2><span class="num">05</span> Source &amp; Methodology</h2>
  <p class="section-sub">How this study was built, and how to reproduce it.</p>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
    <div class="acc-card">
      <h3>Quick Start</h3>
      <pre style="font-family:'JetBrains Mono',monospace;font-size:0.78rem;color:var(--text2);line-height:2;overflow-x:auto"><code>git clone &lt;repo-url&gt;
cd Composio
pip install -r requirements.txt

export OPENAI_API_KEY=sk-...
export TAVILY_API_KEY=tvly-...
export COMPOSIO_API_KEY=ak-...  # optional

python run_pipeline.py</code></pre>
    </div>
    <div class="acc-card">
      <h3>Key Files</h3>
      <ul style="font-size:0.83rem;color:var(--text2);padding-left:1.2em;line-height:2.1">
        <li><code>data/apps_master_list.json</code> — 100-app input</li>
        <li><code>data/pass1_results.json</code> — Researcher output</li>
        <li><code>data/composio_crosscheck.json</code> — Composio coverage</li>
        <li><code>verification/human_checklist.csv</code> — Human fills this</li>
        <li><code>verification/accuracy_report.json</code> — Field accuracy</li>
        <li><code>data/final_results.json</code> — Corrected dataset</li>
        <li><code>data/patterns.json</code> — Pattern analysis</li>
      </ul>
    </div>
  </div>
</section>

<footer>
  <p>Generated by a 3-agent Agno pipeline · OpenAI GPT-4o · Tavily Search · {generated_at}</p>
  <p style="margin-top:8px"><a href="https://github.com" target="_blank">📁 Source Repository</a> · <a href="https://composio.dev" target="_blank">Composio</a></p>
</footer>

<script>
// ── Filters ──────────────────────────────────────────────
function applyFilters() {{
  const cat = document.getElementById('filter-cat').value;
  const verdict = document.getElementById('filter-verdict').value;
  const ss = document.getElementById('filter-ss').value;
  const search = document.getElementById('filter-search').value.toLowerCase().trim();

  const rows = document.querySelectorAll('#table-body tr');
  let visible = 0;

  rows.forEach(row => {{
    if (row.classList.contains('cat-header')) {{
      // Cat headers shown conditionally below
      return;
    }}
    const rowCat = row.dataset.category || '';
    const rowVerdict = row.dataset.verdict || '';
    const rowSs = row.dataset.ss || '';
    const rowText = row.textContent.toLowerCase();

    const show =
      (!cat || rowCat === cat) &&
      (!verdict || rowVerdict === verdict) &&
      (!ss || rowSs === ss) &&
      (!search || rowText.includes(search));

    row.classList.toggle('hidden', !show);
    if (show) visible++;
  }});

  // Show/hide cat headers based on whether they have visible siblings
  document.querySelectorAll('#table-body tr.cat-header').forEach(header => {{
    let next = header.nextElementSibling;
    let hasVisible = false;
    while (next && !next.classList.contains('cat-header')) {{
      if (!next.classList.contains('hidden')) hasVisible = true;
      next = next.nextElementSibling;
    }}
    header.classList.toggle('hidden', !hasVisible);
  }});

  document.getElementById('row-count').textContent = `Showing ${{visible}} of 100 apps`;
}}

// Run on load
applyFilters();

// ── Sort ─────────────────────────────────────────────────
let sortState = {{col: -1, dir: 1}};

function sortTable(col) {{
  const tbody = document.getElementById('table-body');
  const headers = document.querySelectorAll('#app-table thead th');

  if (sortState.col === col) {{
    sortState.dir *= -1;
  }} else {{
    sortState.col = col;
    sortState.dir = 1;
  }}

  headers.forEach((h, i) => {{
    h.classList.remove('sorted-asc', 'sorted-desc');
    if (i === col) h.classList.add(sortState.dir === 1 ? 'sorted-asc' : 'sorted-desc');
  }});

  // Collect app rows (non-cat-header) per category group
  const catHeaders = Array.from(tbody.querySelectorAll('tr.cat-header'));
  const groups = [];
  catHeaders.forEach(header => {{
    const appRows = [];
    let next = header.nextElementSibling;
    while (next && !next.classList.contains('cat-header')) {{
      appRows.push(next);
      next = next.nextElementSibling;
    }}
    groups.push({{header, appRows}});
  }});

  // Sort within each group
  groups.forEach(g => {{
    g.appRows.sort((a, b) => {{
      const aVal = a.cells[col]?.textContent.trim().toLowerCase() || '';
      const bVal = b.cells[col]?.textContent.trim().toLowerCase() || '';
      return aVal.localeCompare(bVal) * sortState.dir;
    }});
    tbody.appendChild(g.header);
    g.appRows.forEach(r => tbody.appendChild(r));
  }});
}}
</script>
</body>
</html>"""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    console.print(f"[bold green]HTML case study generated![/bold green] → {output_path}")
    return output_path
