"""
main.py — DataBro API
=====================
FastAPI application entry point.
All route logic is in api/ modules; this file wires everything together.

Run locally:   uvicorn main:app --reload
Run on Render: set startCommand = uvicorn main:app --host 0.0.0.0 --port $PORT
"""
import os, json, uuid, io
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from core.config import settings
from core.auth import (
    create_session, create_magic_token, consume_magic_token,
    get_current_user, invalidate_session, active_session_count, SESSIONS
)
from models.schemas import (
    MagicLinkRequest, VerifyTokenRequest, RegisterRequest,
    ChatRequest, AnalysisRequest, CorrelateRequest, AgentConfig, CustomAgentCreate
)
from services.file_service import (
    allowed_file, save_upload, parse_file, build_schema,
    build_data_context, numeric_summary, UPLOAD_DIR
)
from services.claude_service import (
    chat as claude_chat, stream_chat, run_analysis, generate_agent_prompt
)

# ── App init ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="DataBro API",
    version="2.0.0",
    description="Agentic AI data analysis platform — upload data, chat with it, generate insights.",
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory stores (replace with Redis + Postgres in production) ─────────────
USER_DATASETS: Dict[str, List[dict]] = {}
AGENT_CONFIGS: Dict[str, dict] = {}      # key: f"{user_id}_{agent_id}"
CUSTOM_AGENTS: Dict[str, List[dict]] = {}  # key: user_id

# Default agent system prompts
DEFAULT_PROMPTS = {
    "sales": """You are the Sales Planner agent for DataBro. You have FULL ACCESS to all uploaded datasets — every row is provided. NEVER ask the user to paste data.

Tasks:
- Compile sales totals by rep name, state, city, region, customer segment
- Identify top performers, geographic concentration, uncovered territories
- Flag mismatches between rep submissions and the customer database
- Answer questions with specific numbers from the data

Output: Lead with a markdown table, then 3 numbered insights with exact figures.""",

    "finance": """You are the Finance Guardian agent for DataBro. You have FULL ACCESS to all uploaded datasets. NEVER ask the user to paste data.

Tasks:
- Compute net cashflow = total revenue - total payables using actual column values
- Identify overdue vendor payments with specific amounts
- Compare inventory value against sales velocity; name slow-moving items
- Flag anomalies with specific row-level examples

Output: KPI table with real numbers first, then 3 concrete action items.""",

    "inventory": """You are the Inventory Auditor agent for DataBro. You have FULL ACCESS to all uploaded datasets. NEVER ask the user to paste data.

Tasks:
- Identify common key fields and list specific matching values
- Surface exact discrepancies: items present in one dataset but missing from another
- Flag duplicate rows, null values, and type mismatches with specific examples
- Provide a data quality score per dataset (0–100)

Output: Schema summary table → exact discrepancy list → quality scorecard.""",
}


# ── Auth routes ───────────────────────────────────────────────────────────────

@app.post("/auth/magic-link", tags=["Auth"])
async def send_magic_link(req: MagicLinkRequest):
    """Generate magic link. In production: email it. In dev: returns token directly."""
    token = create_magic_token(req.email)
    magic_url = f"{settings.app_url}/auth?token={token}"
    # TODO: send email via settings.email_provider
    response = {"success": True, "message": f"Magic link sent to {req.email}"}
    if not settings.is_production:
        response["dev_token"] = token  # Remove in production
        response["dev_url"] = magic_url
    return response


@app.post("/auth/verify", tags=["Auth"])
async def verify_magic_link(req: VerifyTokenRequest):
    email = consume_magic_token(req.token)
    if not email:
        raise HTTPException(400, "Invalid or expired link. Please request a new one.")
    token = create_session(email)
    return {"token": token, "user": SESSIONS[token]}


@app.post("/auth/register", tags=["Auth"])
async def register(
    email: str = Form(...),
    name: str = Form(...),
    company: str = Form(""),
    industry: str = Form(""),
):
    token = create_session(email, name=name, company=company, industry=industry)
    USER_DATASETS.setdefault(_uid(SESSIONS[token]), [])
    return {"token": token, "user": SESSIONS[token]}


@app.post("/auth/demo", tags=["Auth"])
async def demo_login():
    token = create_session("demo@databro.ai", name="Demo User", company="DataBro Demo")
    USER_DATASETS.setdefault(_uid(SESSIONS[token]), [])
    return {"token": token, "user": SESSIONS[token]}


@app.get("/auth/me", tags=["Auth"])
async def get_me(user=Depends(get_current_user)):
    return user


@app.post("/auth/logout", tags=["Auth"])
async def logout(user=Depends(get_current_user)):
    invalidate_session(user["token"])
    return {"success": True}


# ── Datasets ──────────────────────────────────────────────────────────────────

def _uid(user: dict) -> str:
    return user["user_id"] if isinstance(user, dict) else user


@app.post("/upload", tags=["Datasets"])
async def upload_file(file: UploadFile = File(...), user=Depends(get_current_user)):
    """Upload CSV, Excel, or JSON. Returns dataset ID + schema."""
    if not allowed_file(file.filename):
        raise HTTPException(400, f"Unsupported file type. Allowed: CSV, Excel (.xlsx/.xls), JSON")

    contents = await file.read()
    if len(contents) > settings.max_upload_bytes:
        raise HTTPException(413, f"File too large. Max size: {settings.max_upload_mb} MB")

    dataset_id = str(uuid.uuid4())[:12]
    try:
        df = parse_file(contents, file.filename)
    except Exception as e:
        raise HTTPException(400, f"Could not parse file: {e}")

    save_path = save_upload(contents, user["user_id"], dataset_id, file.filename)
    schema = build_schema(df)

    meta = {
        "id": dataset_id,
        "name": Path(file.filename).stem,
        "filename": file.filename,
        "type": Path(file.filename).suffix.lstrip(".").lower(),
        "rows": len(df),
        "cols": len(df.columns),
        "columns": list(df.columns),
        "schema": schema,
        "file_path": str(save_path),
        "uploaded_at": datetime.utcnow().isoformat(),
        "user_id": user["user_id"],
    }
    USER_DATASETS.setdefault(user["user_id"], []).append(meta)
    return meta


@app.get("/datasets", tags=["Datasets"])
async def list_datasets(user=Depends(get_current_user)):
    return USER_DATASETS.get(user["user_id"], [])


@app.delete("/datasets/{dataset_id}", tags=["Datasets"])
async def delete_dataset(dataset_id: str, user=Depends(get_current_user)):
    datasets = USER_DATASETS.get(user["user_id"], [])
    ds = next((d for d in datasets if d["id"] == dataset_id), None)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    Path(ds["file_path"]).unlink(missing_ok=True)
    USER_DATASETS[user["user_id"]] = [d for d in datasets if d["id"] != dataset_id]
    return {"success": True}


@app.get("/datasets/{dataset_id}/data", tags=["Datasets"])
async def get_dataset_data(dataset_id: str, rows: int = 100, user=Depends(get_current_user)):
    datasets = USER_DATASETS.get(user["user_id"], [])
    ds = next((d for d in datasets if d["id"] == dataset_id), None)
    if not ds:
        raise HTTPException(404, "Dataset not found")
    try:
        import pandas as pd
        from services.file_service import load_dataframe
        df = load_dataframe(ds["file_path"], nrows=rows)
        df = df.where(pd.notna(df), None)
        return {"columns": list(df.columns), "rows": df.to_dict(orient="records"), "total": ds["rows"]}
    except Exception as e:
        raise HTTPException(500, f"Could not read file: {e}")


# ── Correlations ──────────────────────────────────────────────────────────────

def _score_correlation(col_a, col_b, schema_a, schema_b):
    na = col_a.lower().replace("_", "").replace("-", "").replace(" ", "")
    nb = col_b.lower().replace("_", "").replace("-", "").replace(" ", "")
    score, reasons = 0.0, []
    if na == nb:
        score += 0.9; reasons.append("Exact name match")
    elif na in nb or nb in na:
        score += 0.5; reasons.append("Partial name match")
    id_sfx = ["id", "code", "key", "no", "num", "number", "ref", "idx"]
    if any(na.endswith(x) for x in id_sfx) and any(nb.endswith(x) for x in id_sfx):
        score += 0.3; reasons.append("Both are ID/key fields")
    ta = schema_a.get(col_a, {}).get("type", "")
    tb = schema_b.get(col_b, {}).get("type", "")
    if ta and ta == tb:
        score += 0.1; reasons.append(f"Same type ({ta})")
    sa = set(schema_a.get(col_a, {}).get("sample", []))
    sb = set(schema_b.get(col_b, {}).get("sample", []))
    overlap = len(sa & sb)
    if overlap:
        score += overlap * 0.2; reasons.append(f"{overlap} overlapping sample values")
    return {"score": round(min(score, 1.0), 3), "reasons": reasons}


@app.post("/correlate", tags=["Analysis"])
async def correlate_datasets(req: CorrelateRequest, user=Depends(get_current_user)):
    datasets = USER_DATASETS.get(user["user_id"], [])
    selected = [d for d in datasets if d["id"] in req.dataset_ids]
    if len(selected) < 2:
        raise HTTPException(400, "Need at least 2 datasets to correlate")
    results = []
    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            a, b = selected[i], selected[j]
            for ca in a["columns"]:
                for cb in b["columns"]:
                    r = _score_correlation(ca, cb, a["schema"], b["schema"])
                    if r["score"] > 0.2:
                        results.append({
                            "ds1_id": a["id"], "ds1_name": a["name"],
                            "ds2_id": b["id"], "ds2_name": b["name"],
                            "col1": ca, "col2": cb, **r
                        })
    results.sort(key=lambda x: x["score"], reverse=True)
    return {"correlations": results, "count": len(results)}


# ── Agent config ──────────────────────────────────────────────────────────────

@app.post("/agent/configure", tags=["Agents"])
async def configure_agent(config: AgentConfig, user=Depends(get_current_user)):
    key = f"{user['user_id']}_{config.agent_id}"
    data = config.model_dump()
    data["updated_at"] = datetime.utcnow().isoformat()
    AGENT_CONFIGS[key] = data
    # Also persist to disk
    cfg_path = Path("agent_configs")
    cfg_path.mkdir(exist_ok=True)
    (cfg_path / f"{key}.json").write_text(json.dumps(data, indent=2))
    return {"success": True, "config": data}


@app.get("/agent/config/{agent_id}", tags=["Agents"])
async def get_agent_config(agent_id: str, user=Depends(get_current_user)):
    key = f"{user['user_id']}_{agent_id}"
    if key in AGENT_CONFIGS:
        return AGENT_CONFIGS[key]
    cfg_path = Path("agent_configs") / f"{key}.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text())
    return {
        "agent_id": agent_id,
        "system_prompt": DEFAULT_PROMPTS.get(agent_id, "You are a helpful data analysis agent."),
        "extra_instructions": "", "dataset_ids": [],
    }


# ── Custom agent builder ──────────────────────────────────────────────────────

@app.post("/agents/custom", tags=["Custom Agents"])
async def create_custom_agent(req: CustomAgentCreate, user=Depends(get_current_user)):
    """Create a new custom agent from the builder wizard."""
    agent_id = "custom_" + str(uuid.uuid4())[:8]
    prompt = generate_agent_prompt(
        name=req.name, description=req.description,
        actions=req.actions, params=req.params,
        outputs=req.outputs, infographic_styles=req.infographic_style,
        extra_instructions=req.extra_instructions,
    )
    agent = {
        "id": agent_id, "name": req.name, "description": req.description,
        "icon": req.icon, "color": req.color, "sources": req.sources,
        "clean": req.clean, "actions": req.actions, "outputs": req.outputs,
        "share_destinations": req.share_destinations,
        "infographic_style": req.infographic_style,
        "extra_instructions": req.extra_instructions, "params": req.params,
        "system_prompt": prompt, "is_custom": True,
        "created_at": datetime.utcnow().isoformat(),
        "user_id": user["user_id"],
    }
    CUSTOM_AGENTS.setdefault(user["user_id"], []).append(agent)
    # Also save as agent config
    AGENT_CONFIGS[f"{user['user_id']}_{agent_id}"] = {
        "agent_id": agent_id, "name": req.name, "icon": req.icon,
        "system_prompt": prompt, "extra_instructions": req.extra_instructions,
        "dataset_ids": [], "is_custom": True,
    }
    return agent


@app.get("/agents/custom", tags=["Custom Agents"])
async def list_custom_agents(user=Depends(get_current_user)):
    return CUSTOM_AGENTS.get(user["user_id"], [])


@app.delete("/agents/custom/{agent_id}", tags=["Custom Agents"])
async def delete_custom_agent(agent_id: str, user=Depends(get_current_user)):
    agents = CUSTOM_AGENTS.get(user["user_id"], [])
    CUSTOM_AGENTS[user["user_id"]] = [a for a in agents if a["id"] != agent_id]
    AGENT_CONFIGS.pop(f"{user['user_id']}_{agent_id}", None)
    return {"success": True}


# ── Chat ──────────────────────────────────────────────────────────────────────

@app.post("/agent/chat", tags=["Chat"])
async def agent_chat(req: ChatRequest, user=Depends(get_current_user)):
    """Chat with a DataBro agent. Supports streaming via req.stream=True."""
    key = f"{user['user_id']}_{req.agent_id}"
    config = AGENT_CONFIGS.get(key, {})
    system = config.get("system_prompt") or DEFAULT_PROMPTS.get(req.agent_id, "You are a helpful data analyst.")
    if config.get("extra_instructions"):
        system += f"\n\nEXTRA INSTRUCTIONS:\n{config['extra_instructions']}"

    # Inject full dataset context
    datasets = USER_DATASETS.get(user["user_id"], [])
    active_ds = [d for d in datasets if d["id"] in req.dataset_ids] if req.dataset_ids else datasets
    if active_ds:
        system += build_data_context(active_ds, user["user_id"])

    messages = [{"role": m.role, "content": m.content} for m in req.history[-20:]]
    messages.append({"role": "user", "content": req.message})

    if req.stream:
        return StreamingResponse(
            stream_chat(system, messages),
            media_type="text/event-stream"
        )

    result = claude_chat(system, messages)
    return result


# ── Agent run ─────────────────────────────────────────────────────────────────

@app.post("/agent/run", tags=["Analysis"])
async def run_agent(req: AnalysisRequest, user=Depends(get_current_user)):
    """Run full structured analysis. Returns JSON with KPIs, insights, tables."""
    datasets = USER_DATASETS.get(user["user_id"], [])
    selected = [d for d in datasets if d["id"] in req.dataset_ids]
    if not selected:
        raise HTTPException(400, "No matching datasets found.")

    summaries = []
    for ds in selected:
        try:
            summaries.append(numeric_summary(ds["file_path"]))
        except Exception as e:
            summaries.append({"name": ds["name"], "error": str(e)})

    key = f"{user['user_id']}_{req.agent_id}"
    config = AGENT_CONFIGS.get(key, {})
    system = config.get("system_prompt") or DEFAULT_PROMPTS.get(req.agent_id, "You are a data analyst.")
    extra = config.get("extra_instructions", "")

    task_desc = f"Perform a {req.task.replace('_', ' ')} on these datasets.\n{f'User instructions: {extra}' if extra else ''}"
    data_str = json.dumps(summaries, indent=2)

    result = run_analysis(system, data_str, task_desc)
    return {
        "agent_id": req.agent_id,
        "task": req.task,
        "datasets": [d["name"] for d in selected],
        **result,
    }


# ── Agent prompt generator ────────────────────────────────────────────────────

@app.post("/agents/generate-prompt", tags=["Custom Agents"])
async def generate_prompt(req: CustomAgentCreate, user=Depends(get_current_user)):
    """Preview the auto-generated system prompt before creating an agent."""
    prompt = generate_agent_prompt(
        name=req.name, description=req.description,
        actions=req.actions, params=req.params,
        outputs=req.outputs, infographic_styles=req.infographic_style,
        extra_instructions=req.extra_instructions,
    )
    return {"prompt": prompt}


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health():
    return {
        "status": "ok",
        "version": "2.0.0",
        "environment": settings.environment,
        "api_key_set": bool(settings.anthropic_api_key),
        "datasets_in_memory": sum(len(v) for v in USER_DATASETS.values()),
        "active_sessions": active_session_count(),
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/", tags=["System"])
async def root():
    return {
        "message": "DataBro API v2",
        "docs": "/docs",
        "health": "/health",
    }


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=settings.port, reload=True)
