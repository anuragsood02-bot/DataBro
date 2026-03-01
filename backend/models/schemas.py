"""
models/schemas.py
All Pydantic request/response models for the DataBro API.
"""
from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional, List, Dict, Any


# ── Auth ──────────────────────────────────────────────────────────────────────

class MagicLinkRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid email address")
        return v.lower().strip()


class VerifyTokenRequest(BaseModel):
    token: str


class RegisterRequest(BaseModel):
    email: str
    name: str
    company: str = ""
    industry: str = ""


class UserResponse(BaseModel):
    user_id: str
    email: str
    name: str
    company: str = ""
    created_at: str


class AuthResponse(BaseModel):
    token: str
    user: dict


# ── Datasets ──────────────────────────────────────────────────────────────────

class ColumnSchema(BaseModel):
    type: str           # number | string | date
    dtype: str
    unique: int
    nulls: int
    null_pct: float
    is_key: bool
    sample: List[str]


class DatasetMeta(BaseModel):
    id: str
    name: str
    filename: str
    type: str           # csv | xlsx | json
    rows: int
    cols: int
    columns: List[str]
    schema_: Dict[str, dict] = {}
    file_path: str
    uploaded_at: str
    user_id: str


class DatasetPreview(BaseModel):
    columns: List[str]
    rows: List[Dict[str, Any]]
    total: int


# ── Correlations ──────────────────────────────────────────────────────────────

class CorrelateRequest(BaseModel):
    dataset_ids: List[str]


class CorrelationResult(BaseModel):
    ds1_id: str
    ds1_name: str
    ds2_id: str
    ds2_name: str
    col1: str
    col2: str
    score: float
    reasons: List[str]


# ── Agent config ──────────────────────────────────────────────────────────────

class AgentConfig(BaseModel):
    agent_id: str
    name: str
    icon: str = "🤖"
    description: str = ""
    system_prompt: str
    dataset_ids: List[str] = []
    extra_instructions: str = ""
    # Custom agent fields
    is_custom: bool = False
    color: str = "#b8ff57"
    sources: List[str] = []
    actions: List[str] = []
    outputs: List[str] = []
    share_destinations: List[str] = []
    infographic_style: List[str] = ["custom"]


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str       # user | assistant
    content: str


class ChatRequest(BaseModel):
    agent_id: str
    message: str
    history: List[ChatMessage] = []
    dataset_ids: List[str] = []
    stream: bool = False


class ChatResponse(BaseModel):
    reply: str
    input_tokens: int
    output_tokens: int


# ── Agent run / analysis ──────────────────────────────────────────────────────

class AnalysisRequest(BaseModel):
    agent_id: str
    dataset_ids: List[str]
    task: str = "full_analysis"


class KPI(BaseModel):
    label: str
    value: str
    signal: str     # good | warn | bad
    note: str = ""


class AnalysisTable(BaseModel):
    title: str
    columns: List[str]
    rows: List[List[Any]]


class AnalysisResult(BaseModel):
    kpis: List[KPI] = []
    summary: str = ""
    insights: List[str] = []
    tables: List[AnalysisTable] = []
    recommendations: List[str] = []
    warnings: List[str] = []


class RunResponse(BaseModel):
    agent_id: str
    task: str
    datasets: List[str]
    result: AnalysisResult
    tokens_used: int


# ── Custom agents ─────────────────────────────────────────────────────────────

class CustomAgentCreate(BaseModel):
    name: str
    description: str = ""
    icon: str = "✦"
    color: str = "#b8ff57"
    sources: List[str] = ["csv"]
    clean: List[str] = []
    actions: List[str] = ["analyse"]
    outputs: List[str] = ["table"]
    share_destinations: List[str] = ["dashboard"]
    infographic_style: List[str] = ["custom"]
    extra_instructions: str = ""
    params: Dict[str, List[str]] = {}


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    version: str
    api_key_set: bool
    datasets_in_memory: int
    active_sessions: int
    timestamp: str
