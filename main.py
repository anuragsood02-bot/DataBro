"""
DataBro Backend — FastAPI + Anthropic Claude
=============================================
Endpoints:
  POST /auth/magic-link      → send/simulate magic link
  POST /auth/verify          → verify token → return session
  GET  /auth/me              → get current user
  POST /upload               → upload CSV/Excel/JSON file
  GET  /datasets             → list user's datasets
  DELETE /datasets/{id}      → remove a dataset
  GET  /datasets/{id}/data   → preview rows
  POST /correlate            → find correlations across datasets
  POST /agent/configure      → save agent config (instructions + files)
  GET  /agent/config/{name}  → load agent config
  POST /agent/chat           → stream or non-stream chat with Claude
  POST /agent/run            → run agent analysis, return structured output
  GET  /health               → health check
"""

import os, json, uuid, time, hashlib, io
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Header, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

import anthropic

# ── Init ────────────────────────────────────────────────────────────────────
app = FastAPI(title="DataBro API", version="1.0.0", description="AI-powered data analysis agent platform")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

SESSION_DIR = Path("sessions")
SESSION_DIR.mkdir(exist_ok=True)

AGENT_CONFIG_DIR = Path("agent_configs")
AGENT_CONFIG_DIR.mkdir(exist_ok=True)

# In-memory stores (replace with Redis/Postgres in production)
SESSIONS: Dict[str, dict] = {}          # token → user data
MAGIC_TOKENS: Dict[str, str] = {}       # token → email (TTL not enforced here, add in prod)
USER_DATASETS: Dict[str, List[dict]] = {}  # user_id → [dataset_meta]

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# ── Pydantic models ──────────────────────────────────────────────────────────

class MagicLinkRequest(BaseModel):
    email: str

class VerifyTokenRequest(BaseModel):
    token: str

class AgentConfig(BaseModel):
    agent_id: str          # 'sales' | 'finance' | 'inventory' | 'custom'
    name: str
    icon: str = "🤖"
    description: str = ""
    system_prompt: str     # fully customisable by user
    dataset_ids: List[str] = []    # which datasets to include
    extra_instructions: str = ""   # user's custom instructions appended

class ChatRequest(BaseModel):
    agent_id: str
    message: str
    history: List[Dict[str, str]] = []
    dataset_ids: List[str] = []
    stream: bool = False

class AnalysisRequest(BaseModel):
    agent_id: str
    dataset_ids: List[str]
    task: str = "full_analysis"   # full_analysis | correlate | schema | output

class CorrelateRequest(BaseModel):
    dataset_ids: List[str]

# ── Auth helpers ─────────────────────────────────────────────────────────────

def get_current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ")[1]
    user = SESSIONS.get(token)
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or invalid")
    return user

def create_session(email: str, name: str = "", company: str = "") -> str:
    token = str(uuid.uuid4())
    user_id = hashlib.md5(email.encode()).hexdigest()[:12]
    SESSIONS[token] = {
        "token": token,
        "user_id": user_id,
        "email": email,
        "name": name or email.split("@")[0].title(),
        "company": company,
        "created_at": datetime.utcnow().isoformat()
    }
    if user_id not in USER_DATASETS:
        USER_DATASETS[user_id] = []
    return token

# ── Auth routes ───────────────────────────────────────────────────────────────

@app.post("/auth/magic-link")
async def send_magic_link(req: MagicLinkRequest):
    """Generate magic link token. In production, email this link to the user."""
    if not req.email or "@" not in req.email:
        raise HTTPException(400, "Invalid email")
    magic_token = str(uuid.uuid4())
    MAGIC_TOKENS[magic_token] = req.email
    # In production: send email with link like https://yourdomain.com/auth?token={magic_token}
    # For dev/demo: return token directly
    return {
        "success": True,
        "message": f"Magic link sent to {req.email}",
        "dev_token": magic_token,   # REMOVE in production — only for dev
        "link": f"http://localhost:8000/auth/verify-page?token={magic_token}"
    }

@app.post("/auth/verify")
async def verify_magic_link(req: VerifyTokenRequest):
    """Verify magic token, issue session token."""
    email = MAGIC_TOKENS.pop(req.token, None)
    if not email:
        raise HTTPException(400, "Invalid or expired link. Request a new one.")
    session_token = create_session(email)
    user = SESSIONS[session_token]
    return {"token": session_token, "user": user}

@app.post("/auth/register")
async def register(email: str = Form(...), name: str = Form(...), company: str = Form(""), industry: str = Form("")):
    """Register new user + auto-issue session."""
    if not email or "@" not in email:
        raise HTTPException(400, "Invalid email")
    session_token = create_session(email, name, company)
    user = SESSIONS[session_token]
    user["industry"] = industry
    return {"token": session_token, "user": user}

@app.post("/auth/demo")
async def demo_login():
    """Issue a demo session."""
    token = create_session("demo@databro.ai", "Demo User", "DataBro Demo Co")
    return {"token": token, "user": SESSIONS[token]}

@app.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user

@app.post("/auth/logout")
async def logout(user: dict = Depends(get_current_user)):
    SESSIONS.pop(user["token"], None)
    return {"success": True}

# ── Dataset / Upload routes ───────────────────────────────────────────────────

def build_schema(df: pd.DataFrame) -> dict:
    """Build column schema metadata from a DataFrame."""
    schema = {}
    for col in df.columns:
        non_null = df[col].dropna()
        total = len(df)
        unique = int(non_null.nunique())
        nulls = int(df[col].isna().sum())
        sample = non_null.head(5).tolist()
        # Type inference
        dtype = str(df[col].dtype)
        if "int" in dtype or "float" in dtype:
            col_type = "number"
        elif "datetime" in dtype:
            col_type = "date"
        else:
            # try parsing dates
            if non_null.astype(str).str.match(r'\d{4}-\d{2}-\d{2}').sum() > len(non_null) * 0.5:
                col_type = "date"
            else:
                col_type = "string"
        schema[col] = {
            "type": col_type,
            "dtype": dtype,
            "unique": unique,
            "nulls": nulls,
            "null_pct": round(nulls / total * 100, 1) if total else 0,
            "is_key": unique == total and nulls == 0,
            "sample": [str(s) for s in sample[:3]]
        }
    return schema

@app.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user)
):
    """Upload a CSV, Excel, or JSON file. Returns dataset ID + schema."""
    ext = Path(file.filename).suffix.lower()
    allowed = {".csv", ".xlsx", ".xls", ".json"}
    if ext not in allowed:
        raise HTTPException(400, f"Unsupported file type: {ext}. Allowed: {', '.join(allowed)}")

    dataset_id = str(uuid.uuid4())[:12]
    save_path = UPLOAD_DIR / f"{user['user_id']}_{dataset_id}{ext}"

    contents = await file.read()
    save_path.write_bytes(contents)

    # Parse
    try:
        if ext == ".csv":
            df = pd.read_csv(io.BytesIO(contents))
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(io.BytesIO(contents))
        elif ext == ".json":
            data = json.loads(contents)
            df = pd.DataFrame(data if isinstance(data, list) else [data])
        else:
            raise ValueError("Unknown format")
    except Exception as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(400, f"Failed to parse file: {str(e)}")

    schema = build_schema(df)
    meta = {
        "id": dataset_id,
        "name": Path(file.filename).stem,
        "filename": file.filename,
        "type": ext.lstrip("."),
        "rows": len(df),
        "cols": len(df.columns),
        "columns": list(df.columns),
        "schema": schema,
        "file_path": str(save_path),
        "uploaded_at": datetime.utcnow().isoformat(),
        "user_id": user["user_id"]
    }
    USER_DATASETS[user["user_id"]].append(meta)
    return meta

@app.get("/datasets")
async def list_datasets(user: dict = Depends(get_current_user)):
    return USER_DATASETS.get(user["user_id"], [])

@app.delete("/datasets/{dataset_id}")
async def delete_dataset(dataset_id: str, user: dict = Depends(get_current_user)):
    datasets = USER_DATASETS.get(user["user_id"], [])
    ds = next((d for d in datasets if d["id"] == dataset_id), None)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    Path(ds["file_path"]).unlink(missing_ok=True)
    USER_DATASETS[user["user_id"]] = [d for d in datasets if d["id"] != dataset_id]
    return {"success": True}

@app.get("/datasets/{dataset_id}/data")
async def get_dataset_data(
    dataset_id: str,
    rows: int = 100,
    user: dict = Depends(get_current_user)
):
    """Return first N rows as JSON for preview."""
    datasets = USER_DATASETS.get(user["user_id"], [])
    ds = next((d for d in datasets if d["id"] == dataset_id), None)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    try:
        ext = Path(ds["file_path"]).suffix.lower()
        if ext == ".csv":
            df = pd.read_csv(ds["file_path"], nrows=rows)
        elif ext in (".xlsx", ".xls"):
            df = pd.read_excel(ds["file_path"], nrows=rows)
        else:
            df = pd.read_csv(ds["file_path"], nrows=rows)
        df = df.where(pd.notna(df), None)
        return {"columns": list(df.columns), "rows": df.head(rows).to_dict(orient="records"), "total": ds["rows"]}
    except Exception as e:
        raise HTTPException(500, f"Could not read file: {e}")

# ── Correlation engine ────────────────────────────────────────────────────────

def score_correlation(col_a: str, col_b: str, schema_a: dict, schema_b: dict) -> dict:
    """Score how likely two columns are a join key."""
    na = col_a.lower().replace("_", "").replace("-", "").replace(" ", "")
    nb = col_b.lower().replace("_", "").replace("-", "").replace(" ", "")
    score = 0.0
    reasons = []

    if na == nb:
        score += 0.9; reasons.append("Exact name match")
    elif na in nb or nb in na:
        score += 0.5; reasons.append("Partial name match")

    id_suffixes = ["id", "code", "key", "no", "num", "number", "ref", "idx"]
    if any(na.endswith(x) for x in id_suffixes) and any(nb.endswith(x) for x in id_suffixes):
        score += 0.3; reasons.append("Both are ID/key fields")

    sa_type = schema_a.get(col_a, {}).get("type", "")
    sb_type = schema_b.get(col_b, {}).get("type", "")
    if sa_type and sa_type == sb_type:
        score += 0.1; reasons.append(f"Same type ({sa_type})")

    sample_a = set(schema_a.get(col_a, {}).get("sample", []))
    sample_b = set(schema_b.get(col_b, {}).get("sample", []))
    overlap = len(sample_a & sample_b)
    if overlap:
        score += overlap * 0.2; reasons.append(f"{overlap} overlapping sample values")

    return {"score": round(min(score, 1.0), 3), "reasons": reasons}

@app.post("/correlate")
async def correlate_datasets(req: CorrelateRequest, user: dict = Depends(get_current_user)):
    """Find correlations between selected datasets."""
    datasets = USER_DATASETS.get(user["user_id"], [])
    selected = [d for d in datasets if d["id"] in req.dataset_ids]
    if len(selected) < 2:
        raise HTTPException(400, "Need at least 2 datasets to correlate")

    correlations = []
    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            a, b = selected[i], selected[j]
            for col_a in a["columns"]:
                for col_b in b["columns"]:
                    result = score_correlation(col_a, col_b, a["schema"], b["schema"])
                    if result["score"] > 0.2:
                        correlations.append({
                            "ds1_id": a["id"], "ds1_name": a["name"],
                            "ds2_id": b["id"], "ds2_name": b["name"],
                            "col1": col_a, "col2": col_b,
                            **result
                        })
    correlations.sort(key=lambda x: x["score"], reverse=True)
    return {"correlations": correlations, "count": len(correlations)}

# ── Agent config routes ───────────────────────────────────────────────────────

DEFAULT_PROMPTS = {
    "sales": """You are the Sales Planner agent for DataBro.
Your role: Help small organisations compile, map, and analyse sales plans from ground-level reps.
Tasks you perform:
- Map rep-submitted sales plans against the customer master database (customer name, code, state, city, region)
- Compile sales totals by: rep name, state, city, region, customer segment
- Surface top performers, geographic concentration, and uncovered territories
- Flag mismatches between rep submissions and the customer database (unknown customers, missing geo data)
Always reference actual column names from the loaded data. Be concise, actionable, and business-focused.
Output format: structured tables followed by 3 bullet-point insights.""",

    "finance": """You are the Finance Guardian agent for DataBro.
Your role: Analyse financial health by cross-referencing sales, inventory, and vendor payment data.
Tasks you perform:
- Compute net cashflow = total revenue - total payables
- Identify overdue vendor payments and flag high-risk payables
- Compare inventory value against sales velocity (slow-moving stock alert)
- Trend revenue month-over-month from sales data
- Flag anomalies: sudden drops, unusually large payments, negative margins
Always reference actual column names. Output: KPI table first, then narrative analysis, then 3 action items.""",

    "inventory": """You are the Inventory Auditor agent for DataBro.
Your role: Perform comprehensive audit of inventory data across multiple datasets.
Tasks you perform:
- Auto-detect schemas and infer field types
- Identify common identifiers (SKU, product_code, item_id, barcode) across datasets
- Define cross-dataset relationships (1:1, 1:N, N:M)
- Surface discrepancies: items in system A not in system B, quantity mismatches
- Flag data quality issues: nulls, duplicates, type inconsistencies
Output: Schema summary → Relationship map → Discrepancy report → Data quality scorecard.""",

    "custom": """You are a custom DataBro data analysis agent.
Your role is to help the user analyse their data as per their specific instructions.
Always be concise, reference actual column names, and provide actionable insights."""
}

@app.post("/agent/configure")
async def configure_agent(config: AgentConfig, user: dict = Depends(get_current_user)):
    """Save/update agent configuration for a user."""
    config_path = AGENT_CONFIG_DIR / f"{user['user_id']}_{config.agent_id}.json"
    config_data = config.dict()
    config_data["updated_at"] = datetime.utcnow().isoformat()
    config_path.write_text(json.dumps(config_data, indent=2))
    return {"success": True, "config": config_data}

@app.get("/agent/config/{agent_id}")
async def get_agent_config(agent_id: str, user: dict = Depends(get_current_user)):
    """Load agent config — user override or default."""
    config_path = AGENT_CONFIG_DIR / f"{user['user_id']}_{agent_id}.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    # Return default
    default_prompt = DEFAULT_PROMPTS.get(agent_id, DEFAULT_PROMPTS["custom"])
    return {
        "agent_id": agent_id,
        "name": agent_id.title(),
        "system_prompt": default_prompt,
        "extra_instructions": "",
        "dataset_ids": []
    }

@app.get("/agent/configs")
async def list_agent_configs(user: dict = Depends(get_current_user)):
    """List all agent configs for user."""
    configs = []
    for path in AGENT_CONFIG_DIR.glob(f"{user['user_id']}_*.json"):
        configs.append(json.loads(path.read_text()))
    return configs

# ── Build context string from loaded datasets ─────────────────────────────────

def build_data_context(dataset_ids: List[str], user_id: str) -> str:
    datasets = USER_DATASETS.get(user_id, [])
    selected = [d for d in datasets if d["id"] in dataset_ids]
    if not selected:
        return ""
    lines = ["\n\n=== LOADED DATASETS ==="]
    for ds in selected:
        lines.append(f"\nDataset: \"{ds['name']}\" ({ds['rows']} rows × {ds['cols']} cols)")
        lines.append(f"File type: {ds['type']}")
        lines.append("Columns:")
        for col, info in ds["schema"].items():
            key_flag = " [KEY]" if info.get("is_key") else ""
            null_flag = f" [nulls: {info['null_pct']}%]" if info['null_pct'] > 0 else ""
            sample_str = ", ".join(info.get("sample", [])[:3])
            lines.append(f"  - {col} ({info['type']}){key_flag}{null_flag} — sample: {sample_str}")
    lines.append("\n=== END DATASETS ===")
    return "\n".join(lines)

# ── Chat route ───────────────────────────────────────────────────────────────

@app.post("/agent/chat")
async def agent_chat(req: ChatRequest, user: dict = Depends(get_current_user)):
    """Send a message to the Claude agent. Optionally stream the response."""
    if not ANTHROPIC_API_KEY:
        raise HTTPException(400, "ANTHROPIC_API_KEY not set. Set it in your environment.")

    # Load agent config
    config_path = AGENT_CONFIG_DIR / f"{user['user_id']}_{req.agent_id}.json"
    if config_path.exists():
        config = json.loads(config_path.read_text())
    else:
        config = {"system_prompt": DEFAULT_PROMPTS.get(req.agent_id, DEFAULT_PROMPTS["custom"]), "extra_instructions": ""}

    # Build system prompt
    system = config["system_prompt"]
    if config.get("extra_instructions"):
        system += f"\n\nADDITIONAL INSTRUCTIONS FROM USER:\n{config['extra_instructions']}"

    # Add dataset context
    context = build_data_context(req.dataset_ids, user["user_id"])
    if context:
        system += context

    # Build messages
    messages = list(req.history[-20:])  # keep last 20 turns
    messages.append({"role": "user", "content": req.message})

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    if req.stream:
        def stream_response():
            with client.messages.stream(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                system=system,
                messages=messages
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {json.dumps({'text': text})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(stream_response(), media_type="text/event-stream")

    # Non-stream
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=system,
        messages=messages
    )
    return {
        "reply": response.content[0].text,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens
    }

# ── Full agent analysis run ──────────────────────────────────────────────────

@app.post("/agent/run")
async def run_agent(req: AnalysisRequest, user: dict = Depends(get_current_user)):
    """
    Run a full agent analysis task.
    Returns structured output (KPIs + insights + tables).
    """
    if not ANTHROPIC_API_KEY:
        raise HTTPException(400, "ANTHROPIC_API_KEY not set.")

    datasets_meta = USER_DATASETS.get(user["user_id"], [])
    selected = [d for d in datasets_meta if d["id"] in req.dataset_ids]
    if not selected:
        raise HTTPException(400, "No datasets found for the given IDs.")

    # Load actual data for analysis
    data_summaries = []
    for ds in selected:
        try:
            ext = Path(ds["file_path"]).suffix.lower()
            if ext == ".csv":
                df = pd.read_csv(ds["file_path"])
            elif ext in (".xlsx", ".xls"):
                df = pd.read_excel(ds["file_path"])
            else:
                df = pd.read_csv(ds["file_path"])
            # Build numeric summary
            num_cols = df.select_dtypes(include="number").columns.tolist()
            summary = {}
            for col in num_cols[:10]:
                summary[col] = {
                    "sum": float(df[col].sum()),
                    "mean": float(df[col].mean()),
                    "min": float(df[col].min()),
                    "max": float(df[col].max()),
                    "nulls": int(df[col].isna().sum())
                }
            data_summaries.append({
                "name": ds["name"],
                "rows": len(df),
                "columns": list(df.columns),
                "numeric_summary": summary,
                "sample_rows": df.head(5).where(pd.notna(df.head(5)), None).to_dict(orient="records")
            })
        except Exception as e:
            data_summaries.append({"name": ds["name"], "error": str(e)})

    config_path = AGENT_CONFIG_DIR / f"{user['user_id']}_{req.agent_id}.json"
    system_prompt = DEFAULT_PROMPTS.get(req.agent_id, DEFAULT_PROMPTS["custom"])
    extra = ""
    if config_path.exists():
        config = json.loads(config_path.read_text())
        system_prompt = config.get("system_prompt", system_prompt)
        extra = config.get("extra_instructions", "")

    task_prompt = f"""
Perform a {req.task.replace('_', ' ')} on the following datasets.

DATA AVAILABLE:
{json.dumps(data_summaries, indent=2)}

{f'ADDITIONAL USER INSTRUCTIONS: {extra}' if extra else ''}

Respond with a JSON object structured as:
{{
  "kpis": [{{"label": "...", "value": "...", "signal": "good|warn|bad", "note": "..."}}],
  "summary": "2-3 sentence executive summary",
  "insights": ["insight 1", "insight 2", "insight 3"],
  "tables": [
    {{
      "title": "Table title",
      "columns": ["col1", "col2"],
      "rows": [["val1", "val2"]]
    }}
  ],
  "recommendations": ["action 1", "action 2"],
  "warnings": ["warning if any"]
}}

Return ONLY valid JSON. No markdown, no code blocks.
"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system_prompt + build_data_context(req.dataset_ids, user["user_id"]),
        messages=[{"role": "user", "content": task_prompt}]
    )

    raw = response.content[0].text.strip()
    # Strip markdown code fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        result = {"summary": raw, "kpis": [], "insights": [], "tables": [], "recommendations": [], "warnings": []}

    return {
        "agent_id": req.agent_id,
        "task": req.task,
        "datasets": [d["name"] for d in selected],
        "result": result,
        "tokens_used": response.usage.input_tokens + response.usage.output_tokens
    }

# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "1.0.0",
        "api_key_set": bool(ANTHROPIC_API_KEY),
        "datasets_in_memory": sum(len(v) for v in USER_DATASETS.values()),
        "active_sessions": len(SESSIONS),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get("/")
async def root():
    return {"message": "DataBro API — visit /docs for interactive API explorer"}

# ── Run ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
