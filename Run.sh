#!/bin/bash
# DataBro Backend — Setup & Run Script
# =====================================
# Run this once to install deps, then use the start command below.

echo "=== DataBro Backend Setup ==="

# 1. Create virtual environment (recommended)
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Set your Anthropic API key
#    Option A: Export in terminal (lasts until terminal closes)
export ANTHROPIC_API_KEY="sk-ant-YOUR_KEY_HERE"
#    Option B: Create a .env file (safer for dev)
#    echo 'ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_H' > .env

# 4. Start the server
echo "Starting DataBro backend on http://localhost:8000 ..."
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# ── Windows users ──────────────────────────────────────────────────────────
# python -m venv venv
# venv\Scripts\activate
# pip install -r requirements.txt
# set ANTHROPIC_API_KEY=sk-ant-YOUR_KEY_HERE
# uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# ── Quick start (no venv) ──────────────────────────────────────────────────
# ANTHROPIC_API_KEY=sk-ant-xxx uvicorn main:app --reload --port 8000

