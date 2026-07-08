#!/usr/bin/env bash
# run.sh — convenience script that sets env vars and launches the pipeline

export OPENAI_API_KEY="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"
export TAVILY_API_KEY="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"
export COMPOSIO_API_KEY="ak_3J6nQN_eQ1-81fAJlZ8I"

# Use virtualenv if present
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

python3 run_pipeline.py
