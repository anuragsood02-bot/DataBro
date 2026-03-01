"""
services/claude_service.py
All Anthropic Claude API interactions.

Architecture principle:
  The agent prompt does NOT pre-define what tables/breakdowns to produce.
  Instead it gives Claude three things:
    1. WHO it is and WHAT the user wants — verbatim from their setup instructions
    2. The actual data
    3. Strong behavioural rules: understand intent, never refuse, always find a way

  This means Claude reads the user's plain-English instructions AND the real data
  together, then decides what analysis makes sense — just like a smart analyst would.
  We never hard-code "do a rep-wise breakdown" — Claude infers that from "give me
  sales rep wise analysis" because it understands language.
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
    """Non-streaming chat. Returns {reply, input_tokens, output_tokens}."""
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
    """SSE streaming chat. Yields 'data: {...}\\n\\n' strings."""
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
    Structured analysis run — returns parsed JSON.

    The system_prompt already encodes the user's full intent.
    We hand Claude the data and ask it to reason freely, producing
    whatever tables and breakdowns best answer the instructions.
    Claude determines the right output shape from the data + intent together.
    """
    client = _client()

    prompt = f"""Here is the data for you to analyse:

{data_context}

Now perform your complete analysis based on your instructions.

Return ONLY a valid JSON object — no markdown, no code fences, no preamble:
{{
  "summary": "3-4 sentence executive summary with real numbers from the data",
  "kpis": [
    {{"label": "metric name", "value": "actual value", "signal": "good|warn|bad", "note": "brief context"}}
  ],
  "tables": [
    {{
      "title": "descriptive title reflecting what this table shows",
      "columns": ["column header 1", "column header 2"],
      "rows": [["actual value", "actual value"]]
    }}
  ],
  "insights": ["specific finding with number", "specific finding 2", "specific finding 3"],
  "recommendations": ["concrete action based on findings"],
  "warnings": ["data quality issues if any — omit this key if none"]
}}

Important:
- Produce one table per breakdown the user's instructions asked for (rep-wise, geography-wise, customer-wise, product-wise etc)
- Every cell must contain a real value from the data
- kpis should be the 3-6 numbers a decision-maker would want to see immediately
- If a requested dimension/grouping column doesn't exist, note it in warnings and use the closest available column instead"""

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
            "recommendations": [], "warnings": ["Raw text response — structured output unavailable"]
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
    file_descriptions: List[str] = [],
    column_metadata: str = "",
    business_rules: List[str] = [],
    sops: List[str] = [],
    understanding_notes: str = "",
    action_parameters: str = "",
    action_business_rules: List[str] = [],
    action_extra: str = "",
    infographic_notes: str = "",
) -> str:
    """
    Build the system prompt for a custom agent.

    Design philosophy — why we do NOT generate a rigid execution checklist:
    ──────────────────────────────────────────────────────────────────────
    A rigid checklist like "STEP 1: find rep column, STEP 2: group by it" fails because:

    1. We don't know what columns exist until the data arrives at runtime.
       Pre-scripting "group by Rep column" when the actual column is called
       "Sales Person" or "Account Manager" causes silent failure.

    2. The user wrote instructions in plain English because that language is
       flexible and contextual. Paraphrasing it into rigid steps throws away
       that flexibility and introduces our interpretation errors.

    3. Claude is genuinely good at understanding intent from natural language.
       The right move is to pass the instructions through verbatim and let
       Claude reason about how to fulfil them given what it actually sees.

    What we DO give Claude:
    ──────────────────────
    1. The user's exact words — verbatim, not summarised or reinterpreted
    2. Strong behavioural rules: never refuse, always find a way, understand intent
    3. Data behaviour rules: how to handle multiple files, missing columns, etc.
    4. Output format guidance: what types of output to produce

    Claude then reads the actual data AND these instructions together and
    reasons about what analysis is appropriate — exactly as a good analyst would.
    """

    # ── Collect every user instruction verbatim — nothing paraphrased ───────
    instruction_blocks = []

    if description and description.strip():
        instruction_blocks.append(
            f"WHAT THIS AGENT IS BUILT TO DO (user's exact words):\n{description.strip()}"
        )

    if file_descriptions:
        fd_lines = [f"  • {f}" for f in file_descriptions if f and f.strip()]
        if fd_lines:
            instruction_blocks.append(
                "DATA SOURCES THE USER DESCRIBED:\n" + "\n".join(fd_lines)
            )

    if column_metadata and column_metadata.strip():
        instruction_blocks.append(
            f"HOW TO UNDERSTAND THE DATA — column definitions and hints (user's words):\n{column_metadata.strip()}"
        )

    if understanding_notes and understanding_notes.strip():
        instruction_blocks.append(
            f"ADDITIONAL DATA CONTEXT (user's notes):\n{understanding_notes.strip()}"
        )

    # ── Actions: express as intent, not a script ─────────────────────────────
    # We tell Claude what kind of analysis the user wants, not how to do it.
    # Claude decides the how based on what it sees in the data.
    ACT_INTENT = {
        "analyse":   "Analyse the data in depth — compute key metrics, identify patterns, surface what matters most",
        "correlate": "Find meaningful correlations and relationships between variables",
        "flag":      "Identify anomalies, outliers, threshold breaches, and anything that needs attention",
        "reconcile": "Match and reconcile records across sources — surface gaps, mismatches, and discrepancies",
        "forecast":  "Project trends forward — estimate future values based on patterns in the data",
        "rank":      "Rank and score — show top performers, bottom performers, and the gap between them",
        "dedupe":    "Find and list duplicate or near-duplicate records",
        "summarise": "Produce a clear executive summary — the key numbers a decision-maker needs",
    }

    if actions:
        action_lines = []
        for a in actions:
            intent = ACT_INTENT.get(a, f"Perform {a} on the data")
            p = params.get(a, [])
            line = f"  • {intent}"
            if p:
                line += f" — focus on: {', '.join(p)}"
            action_lines.append(line)
        if action_parameters and action_parameters.strip():
            action_lines.append(
                f"  Specific parameters the user mentioned: {action_parameters.strip()}"
            )
        instruction_blocks.append("ANALYSIS TO PERFORM:\n" + "\n".join(action_lines))

    # ── Business rules — passed verbatim, no interpretation ──────────────────
    all_rules = [r.strip() for r in (business_rules + action_business_rules) if r and r.strip()]
    if all_rules:
        rules_text = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(all_rules))
        instruction_blocks.append(
            f"BUSINESS RULES — apply every one without exception:\n{rules_text}"
        )

    active_sops = [s.strip() for s in sops if s and s.strip()]
    if active_sops:
        sop_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(active_sops))
        instruction_blocks.append(
            f"STANDARD OPERATING PROCEDURES — follow these exactly:\n{sop_text}"
        )

    # Free-text extra instructions — verbatim
    extra_parts = [
        x.strip() for x in [action_extra, extra_instructions]
        if x and x.strip()
    ]
    if extra_parts:
        instruction_blocks.append(
            "ADDITIONAL INSTRUCTIONS FROM THE USER:\n" +
            "\n".join(f"  {x}" for x in extra_parts)
        )

    # ── Output format ────────────────────────────────────────────────────────
    OUT_MAP = {
        "table": "data tables", "chart": "charts", "pdf": "PDF report",
        "csv": "downloadable CSV", "email": "email-ready summary", "chat": "conversational summary",
    }
    IG_MAP = {
        "auto": "choose the best chart type for the data",
        "exec": "executive summary card", "heatmap": "performance heatmap",
        "timeline": "trend timeline", "funnel": "funnel / pipeline chart", "scorecard": "scorecard",
    }
    out_line = ", ".join(OUT_MAP.get(o, o) for o in outputs) if outputs else "data tables"
    ig_line  = ", ".join(IG_MAP.get(i, i) for i in infographic_styles) if infographic_styles else "best chart type for the data"

    output_block = f"OUTPUT FORMAT: {out_line}\n"
    output_block += f"INFOGRAPHICS: {ig_line} — always built from analysis results, not raw input files\n"
    if infographic_notes and infographic_notes.strip():
        output_block += f"Infographic guidance: {infographic_notes.strip()}\n"

    instructions_section = "\n\n".join(instruction_blocks)

    return f"""You are {name}, a custom data analysis agent built on DataBro.

════════════════════════════════════════════════════════════════════
YOUR INSTRUCTIONS — READ THESE CAREFULLY BEFORE DOING ANYTHING
════════════════════════════════════════════════════════════════════
{instructions_section}

{output_block}
════════════════════════════════════════════════════════════════════
HOW YOU MUST BEHAVE
════════════════════════════════════════════════════════════════════

ABOUT THE DATA
You will receive the complete dataset(s) directly in the conversation.
Every row is there. Never ask for data to be uploaded, pasted, or described.
Never say "I don't have access to the data" or "the file wasn't provided".

UNDERSTANDING WHAT THE USER WANTS
Read the instructions above carefully. They are written in plain English — understand the meaning, not just the words.

If the user said "sales rep wise" → find whichever column contains person/rep names and group by it. The column might be called "Rep", "Sales Person", "Account Manager", "Employee", "Agent", "Owner" — use whichever one exists.

If the user said "geography wise" → find whichever column contains location data. It might be "City", "State", "Region", "Zone", "Territory", "Area", "Location" — use what's there.

If the user said "customer wise" → find whichever column contains customer/client/account names.

If the user said "compile multiple files" → automatically stack or join the datasets and produce a unified view.

If the user's instructions mention a specific column name that doesn't exist → look for a column that serves the same purpose, use it, and explain what you used.

Never say "that analysis isn't possible". Always find the closest way to answer what was asked.

WORKING WITH MULTIPLE FILES
When multiple datasets are uploaded:
1. Inspect each one — look at its filename, column names, and row samples
2. If they share the same structure → combine/stack them into one unified table
3. If they have different structures → analyse each, then produce a combined summary
4. Use filename, sheet name, or any identifying column to label which file each row came from

PRODUCING OUTPUT
Produce every breakdown and analysis the instructions asked for.
If instructions say "rep-wise, geography-wise, customer-wise" → produce three separate tables, one for each.
Use real numbers. Never leave a cell blank unless the value is genuinely missing in the source data.
Lead with the most important finding. Structure: Summary → Key Numbers → Tables → Insights → Actions.

APPLYING BUSINESS RULES
Apply every business rule listed in your instructions to the actual data.
Flag every row or item that violates a rule — list them explicitly.
If a rule produces no violations, state "No violations found for rule: [rule text]".
════════════════════════════════════════════════════════════════════"""
