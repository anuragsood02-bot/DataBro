"""
services/claude_service.py
All Anthropic Claude API interactions — chat, analysis, prompt generation.
Single place to swap models, tune parameters, add retry logic.
"""
import json
from typing import List, Dict, Generator, Optional

import anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from core.config import settings


def _client() -> anthropic.Anthropic:
    if not settings.anthropic_api_key:
        raise ValueError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def chat(
    system: str,
    messages: List[Dict[str, str]],
    max_tokens: int = None,
    model: str = None,
) -> Dict:
    """
    Non-streaming chat call. Returns {reply, input_tokens, output_tokens}.
    Retries up to 3x on transient errors (rate limits, network issues).
    """
    client = _client()
    response = client.messages.create(
        model=model or settings.claude_model,
        max_tokens=max_tokens or settings.claude_max_tokens,
        system=system,
        messages=messages,
    )
    return {
        "reply": response.content[0].text,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
    }


def stream_chat(
    system: str,
    messages: List[Dict[str, str]],
    max_tokens: int = None,
    model: str = None,
) -> Generator[str, None, None]:
    """
    Server-sent events generator for streaming chat.
    Yields SSE-formatted strings: 'data: {...}\\n\\n'
    """
    client = _client()
    with client.messages.stream(
        model=model or settings.claude_model,
        max_tokens=max_tokens or settings.claude_max_tokens,
        system=system,
        messages=messages,
    ) as stream:
        for text in stream.text_stream:
            yield f"data: {json.dumps({'text': text})}\n\n"
    yield "data: [DONE]\n\n"


@retry(stop=stop_after_attempt(2), wait=wait_exponential(min=2, max=8))
def run_analysis(
    system_prompt: str,
    data_context: str,
    task_description: str,
    model: str = None,
) -> Dict:
    """
    Structured analysis run — returns parsed JSON result dict.
    Used by /agent/run endpoint.
    """
    client = _client()
    prompt = f"""{task_description}

DATA:
{data_context}

Respond ONLY with a valid JSON object — no markdown, no code fences, no commentary.
JSON structure:
{{
  "kpis": [{{"label": "...", "value": "...", "signal": "good|warn|bad", "note": "..."}}],
  "summary": "2-3 sentence executive summary with specific numbers",
  "insights": ["specific insight with numbers", "insight 2", "insight 3"],
  "tables": [{{"title": "...", "columns": ["col1", "col2"], "rows": [["v1", "v2"]]}}],
  "recommendations": ["concrete action 1", "action 2"],
  "warnings": ["warning if any data issues"]
}}"""

    response = client.messages.create(
        model=model or settings.claude_model,
        max_tokens=settings.claude_max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "summary": raw,
            "kpis": [], "insights": [], "tables": [],
            "recommendations": [], "warnings": ["Could not parse structured output"]
        }

    return {
        "result": result,
        "tokens_used": response.usage.input_tokens + response.usage.output_tokens,
    }


def generate_agent_prompt(
    name: str,
    description: str,
    actions: List[str],
    params: Dict[str, List[str]],
    outputs: List[str],
    infographic_styles: List[str],
    extra_instructions: str = "",
) -> str:
    """
    Auto-generate a system prompt for a custom agent from its config.
    Called by the agent builder wizard.
    """
    ACT_MAP = {
        "analyse":   "Analyse the following parameters in depth",
        "correlate": "Find correlations between datasets",
        "flag":      "Flag anomalies and threshold breaches",
        "reconcile": "Reconcile records and surface discrepancies",
        "forecast":  "Produce trend analysis and forward projections",
        "rank":      "Score and rank items by performance criteria",
        "dedupe":    "Identify and remove duplicate or inconsistent records",
        "summarise": "Generate executive summary with pivot breakdowns",
    }
    OUT_MAP = {
        "table": "Data Table", "chart": "Charts", "pdf": "PDF Report",
        "csv": "Export CSV", "email": "Email Report", "chat": "Chat Summary",
    }
    IG_MAP = {
        "exec": "Executive Summary card", "heatmap": "Performance Heatmap",
        "timeline": "Trend Timeline", "funnel": "Funnel/Pipeline chart",
        "scorecard": "Scorecard", "custom": "Auto (best format for data)",
    }

    act_lines = []
    for a in actions:
        p = params.get(a, [])
        line = f"- {ACT_MAP.get(a, a)}"
        if p:
            line += f": {', '.join(p)}"
        act_lines.append(line)

    out_line = ", ".join(OUT_MAP.get(o, o) for o in outputs)
    ig_line  = ", ".join(IG_MAP.get(i, i)  for i in infographic_styles)
    extra    = f"\n\nAdditional instructions:\n{extra_instructions}" if extra_instructions else ""

    return f"""You are {name}, a custom DataBro agentic AI.
Role: {description or 'Analyse the uploaded data and generate actionable business insights.'}

CRITICAL: You have FULL ACCESS to all uploaded datasets — every row is provided directly in this conversation. \
NEVER ask the user to paste data or describe their files. Always compute answers directly from the data rows provided.

Your tasks:
{chr(10).join(act_lines)}

Output format: {out_line}
Infographic style: {ig_line}

Always lead with a summary table, then numbered insights with specific figures from the data.{extra}"""
