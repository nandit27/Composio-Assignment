# AI-Agent Toolkit Readiness: 100 SaaS Apps

> A 3-agent agentic research pipeline that analyzes 100 real-world SaaS and developer tool apps to determine whether each can become a Composio-style AI-agent connector **today**.

## Architecture

```
data/apps_master_list.json
        │
        ▼
┌───────────────────┐
│  Agent 1          │  OpenAI GPT-4o + Tavily Search + fetch_page
│  RESEARCHER       │  → data/pass1_results.json
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  Agent 2          │  Composio Python SDK
│  COMPOSIO         │  → data/composio_crosscheck.json
│  CROSS-CHECK      │
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  Agent 3          │  GPT-4o + alternative search strategy
│  VERIFIER         │  → verification/human_checklist.csv
└───────────────────┘
        │
        ▼ ⏸ HUMAN PAUSE (fill in human_checklist.csv)
        │
        ▼
┌───────────────────┐
│  Accuracy         │  Field-level accuracy computation
│  Computer         │  → verification/accuracy_report.json
│                   │  → data/final_results.json
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  Pattern          │  → data/patterns.json
│  Analyzer         │
└───────────────────┘
        │
        ▼
┌───────────────────┐
│  HTML Builder     │  → output/case_study.html
└───────────────────┘
```

## Setup

### 1. Get API Keys

- **OpenAI**: Sign up at [platform.openai.com](https://platform.openai.com) and create an API key
- **Tavily**: Sign up at [tavily.com](https://tavily.com) and get your API key (free tier available)
- **Composio** *(optional)*: Sign up manually at [composio.dev](https://composio.dev) — do NOT use any auto-signup tool. After signing in, go to Settings → API Keys to copy your key

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Set Environment Variables

```bash
export OPENAI_API_KEY=sk-...
export TAVILY_API_KEY=tvly-...
export COMPOSIO_API_KEY=ak-...   # optional — skip for Composio cross-check
```

### 4. Run the Pipeline

```bash
python run_pipeline.py
```

## Pipeline Stages

| Stage | Output File | Description |
|-------|-------------|-------------|
| Agent 1 — Researcher | `data/pass1_results.json` | Searches + scrapes docs for 100 apps |
| Agent 2 — Composio Check | `data/composio_crosscheck.json` | Checks Composio catalog coverage |
| Agent 3 — Verifier | `verification/human_checklist.csv` | Re-checks 20 apps, generates CSV |
| ⏸ **HUMAN PAUSE** | — | Fill in `human_checklist.csv`, then type `continue` |
| Accuracy Computer | `verification/accuracy_report.json` | Computes field-level accuracy |
| Pattern Analyzer | `data/patterns.json` | Generates statistics and insights |
| HTML Builder | `output/case_study.html` | Generates the self-contained case study |

## Human Verification Step

After Agent 3 runs, the pipeline **pauses** and prints:

```
Fill in verification/human_checklist.csv, then say 'continue'.
```

Open `verification/human_checklist.csv` and fill in the `human_verified_correct_answer` column for each row by visiting the real developer documentation for each sampled app. The checklist contains 20 apps × 6 fields = 120 rows.

Once done, type `continue` in the terminal to resume.

## Output

- **`output/case_study.html`** — Self-contained HTML case study (open in any browser, no server needed)
- **`data/final_results.json`** — Corrected dataset for all 100 apps
- **`verification/accuracy_report.json`** — Field-level accuracy metrics

## Skipping Stages

If any output file already exists, that stage is automatically skipped. Delete the relevant file to force a re-run of that stage:

```bash
rm data/pass1_results.json        # re-run Researcher
rm data/composio_crosscheck.json  # re-run Composio check
rm verification/human_checklist.csv  # re-run Verifier
rm data/final_results.json        # re-run accuracy computation
```

## File Structure

```
Composio/
├── data/
│   ├── apps_master_list.json       ← input: 100 apps
│   ├── pass1_results.json          ← Agent 1 output
│   ├── composio_crosscheck.json    ← Agent 2 output
│   ├── final_results.json          ← corrected final dataset
│   └── patterns.json               ← pattern analysis
├── verification/
│   ├── human_checklist.csv         ← human fills this in
│   └── accuracy_report.json        ← field-level accuracy
├── agents/
│   ├── models.py                   ← shared Pydantic models
│   ├── researcher.py               ← Agent 1
│   ├── composio_checker.py         ← Agent 2
│   ├── verifier.py                 ← Agent 3
│   └── accuracy_computer.py        ← post-human accuracy step
├── analysis/
│   ├── pattern_analyzer.py         ← statistics + insights
│   └── html_builder.py             ← HTML case study generator
├── output/
│   └── case_study.html             ← deliverable
├── run_pipeline.py                 ← main orchestrator
├── requirements.txt
└── README.md
```
