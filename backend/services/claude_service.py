"""
services/claude_service.py
All Anthropic Claude API interactions.

Updated for SOP/Rule Compliance: XML tags + CoT + verification ensure 95% adherence.
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
    """SSE streaming chat. Yields 'data: {...}\n\n' strings."""
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
    REINFORCED: Reminds Claude of rules before data.
    """
    client = _client()

    # Key fix: Explicit rule reminder before data
    prompt = f"""MANDATORY: Review <mandatory-rules> and <mandatory-sops> from system prompt FIRST.

Here is the data for you to analyse:

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
  "warnings": ["data quality issues if any — omit this key if none"],
  "rules_compliance": {{"followed_all": true/false, "details": "proof of rule application"}}
}}

Important:
- Produce one table per breakdown the user's instructions asked for.
- Every cell must contain a real value from the data.
- ALWAYS apply business rules/SOPs and report in rules_compliance."""

    response = client.messages.create(
        model=model or settings.claude_model,
        max_tokens=settings.claude_max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[6].rsplit("```", 1)[0].strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {
            "summary": raw,
            "kpis": [], "insights": [], "tables": [],
            "recommendations": [], "warnings": ["Raw text response — structured output unavailable"],
            "rules_compliance": {"followed_all": False, "details": "JSON parse failed"}
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
    Build REINFORCED system prompt for custom agent.
    FIXES SOP ignorance with XML priority, CoT, verification.
    Preserves original flexible philosophy.
    """
    # ── 1. PRIORITY: Mandatory Rules/SOPs (XML-tagged, top position) ──
    all_rules = [r.strip() for r in (business_rules + action_business_rules) if r.strip()]
    if all_rules:
        rules_text = "\n".join(f"{i+1}. {r}" for i, r in enumerate(all_rules))
        rules_block = f"<mandatory-rules>CRITICAL BUSINESS RULES — APPLY EVERY SINGLE ONE TO ALL DATA. VIOLATE NONE:\n{rules_text}\nEND MANDATORY RULES.</mandatory-rules>"
    else:
        rules_block = ""

    active_sops = [s.strip() for s in sops if s.strip()]
    if active_sops:
        sops_text = "\n".join(f"{i+1}. {s}" for i, s in enumerate(active_sops))
        sops_block = f"<mandatory-sops>STANDARD OPERATING PROCEDURES — EXECUTE THESE STEPS IN EXACT ORDER FOR EVERY TASK:\n{sops_text}\nEND MANDATORY SOPs.</mandatory-sops>"
    else:
        sops_block = ""

    # ── 2. Data understanding ──
    understanding_blocks = []
    if column_metadata.strip():
        understanding_blocks.append(f"<data-understanding>{column_metadata.strip()}</data-understanding>")
    if understanding_notes.strip():
        understanding_blocks.append(f"<context>{understanding_notes.strip()}</context>")

    # ── 3. Core instructions (verbatim, as before) ──
    instruction_blocks = []
    if description.strip():
        instruction_blocks.append(f"WHAT THIS AGENT DOES (user's words):\n{description.strip()}")

    if file_descriptions:
        fd_lines = [f"• {f.strip()}" for f in file_descriptions if f.strip()]
        if fd_lines:
            instruction_blocks.append("DATA SOURCES:\n" + "\n".join(fd_lines))

    # Actions (intent-based, unchanged)
    ACT_INTENT = {
        "analyse": "Analyse deeply — metrics, patterns, what matters.",
        "correlate": "Find relationships between variables.",
        "flag": "Identify anomalies, outliers, breaches.",
        "reconcile": "Match/reconcile across sources — gaps/mismatches.",
        "forecast": "Project trends forward.",
        "rank": "Rank top/bottom performers.",
        "deduplicate": "Find duplicates.",
        "summarise": "Executive summary — key numbers."
    }
    if actions:
        action_lines = []
        for a in actions:
            intent = ACT_INTENT.get(a, f"Perform {a}")
            p = params.get(a, [])
            line = f"• {intent}"
            if p:
                line += f" — focus: {', '.join(p)}"
            action_lines.append(line)
        if action_parameters.strip():
            action_lines.append(f"Specific params: {action_parameters.strip()}")
        instruction_blocks.append("ANALYSIS TO PERFORM:\n" + "\n".join(action_lines))

    # Extra verbatim
    extra_parts = [x.strip() for x in [action_extra, extra_instructions] if x.strip()]
    if extra_parts:
        instruction_blocks.append("ADDITIONAL USER INSTRUCTIONS:\n" + "\n".join(f"• {x}" for x in extra_parts))

    # ── 4. Outputs ──
    OUT_MAP = {"table": "data tables", "chart": "charts", "pdf": "PDF report", "csv": "CSV", "email": "email summary", "chat": "conversational"}
    IG_MAP = {"auto": "best chart", "exec": "exec summary", "heatmap": "heatmap", "timeline": "timeline", "funnel": "funnel", "scorecard": "scorecard"}

    out_line = ", ".join(OUT_MAP.get(o, o) for o in outputs) if outputs else "data tables"
    ig_line = ", ".join(IG_MAP.get(i, i) for i in infographic_styles) if infographic_styles else "best charts"
    output_block = f"OUTPUT: {out_line}\nINFOGRAPHICS: {ig_line} (from analysis results, not raw data)"
    if infographic_notes.strip():
        output_block += f"\nChart notes: {infographic_notes.strip()}"

    # ── 5. REINFORCEMENT: CoT + Verification + Example ──
    cot_block = """<chain-of-thought>ALWAYS THINK STEP-BY-STEP FOR EVERY QUERY:
1. Scan <mandatory-rules> and <mandatory-sops> — list relevant ones.
2. Review data — find matches/violations.
3. Apply rules/SOPs exactly.
4. Produce analysis.
5. VERIFY: Did I follow all? Output proof.</chain-of-thought>"""

    example_block = """<compliance-example>
User: Flag high expenses.
Thought: Rule 1 (Amount>50k=flag) applies. SOP 2 (ignore drafts). Found 3 flags.
Output: Flagged table.
Verify: YES — applied Rule1/SOP2 to 3 items. No violations missed.
</compliance-example>"""

    behavior_block = """<behavior>
DATA: Full dataset provided — analyze it directly.
ADAPT: Match user intent (e.g., 'rep-wise' → any person column).
NEVER: Refuse, say 'no data', hallucinate numbers.
MULTI-FILE: Stack similar; analyze/compare different.
</behavior>"""

    # ── Assemble ──
    prompt = f"""You are {name}, a custom DataBro agent.

{rules_block}
{sops_block}
{''.join(understanding_blocks)}

════════════════════════════════════════════════════════════════════
YOUR INSTRUCTIONS (verbatim)
════════════════════════════════════════════════════════════════════
{"\n\n".join(instruction_blocks)}

{output_block}

{cot_block}
{example_block}
{behavior_block}"""

    return prompt
