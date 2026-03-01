# DataBro API Reference

Base URL: `https://databro-api.onrender.com` (production) or `http://localhost:8000` (local)

Interactive docs: `GET /docs` (Swagger UI) or `GET /redoc`

---

## Authentication

All protected endpoints require:
```
Authorization: Bearer <token>
```

### POST /auth/demo
Get a demo session instantly — no email required.

**Response:**
```json
{ "token": "uuid", "user": { "user_id": "...", "email": "demo@databro.ai", "name": "Demo User" } }
```

### POST /auth/magic-link
```json
{ "email": "user@company.com" }
```
In dev mode returns `dev_token`. In production, emails a magic link.

### POST /auth/verify
```json
{ "token": "<magic_token>" }
```

### POST /auth/register
Form data: `email`, `name`, `company`, `industry`

### GET /auth/me
Returns current user object.

### POST /auth/logout
Invalidates the current session.

---

## Datasets

### POST /upload
Upload a CSV, Excel (.xlsx/.xls), or JSON file.
- Content-Type: `multipart/form-data`
- Field: `file`
- Max size: 25 MB (configurable)

**Response:**
```json
{
  "id": "abc123",
  "name": "sales_data",
  "rows": 1500,
  "cols": 12,
  "columns": ["Date", "Region", "Sales", ...],
  "schema": { "Date": { "type": "date", ... } },
  "uploaded_at": "2024-01-15T10:30:00"
}
```

### GET /datasets
List all datasets for the current user.

### DELETE /datasets/{id}
Remove a dataset (also deletes the uploaded file).

### GET /datasets/{id}/data?rows=100
Preview up to N rows as JSON.

---

## Analysis

### POST /correlate
Find correlations between datasets.
```json
{ "dataset_ids": ["abc123", "def456"] }
```

**Response:**
```json
{
  "correlations": [
    { "ds1_name": "sales", "ds2_name": "customers", "col1": "customer_id", "col2": "id", "score": 0.95, "reasons": ["Exact name match", "Both are ID fields"] }
  ],
  "count": 5
}
```

### POST /agent/run
Run full structured analysis.
```json
{
  "agent_id": "finance",
  "dataset_ids": ["abc123", "def456"],
  "task": "full_analysis"
}
```

**Response:**
```json
{
  "result": {
    "kpis": [{ "label": "Net Cashflow", "value": "₹12.4L", "signal": "good", "note": "..." }],
    "summary": "...",
    "insights": ["insight 1", "insight 2", "insight 3"],
    "tables": [{ "title": "Revenue by Region", "columns": ["Region", "Amount"], "rows": [...] }],
    "recommendations": ["action 1", "action 2"],
    "warnings": []
  },
  "tokens_used": 2847
}
```

---

## Chat

### POST /agent/chat
```json
{
  "agent_id": "finance",
  "message": "Which region has the highest sales?",
  "dataset_ids": ["abc123"],
  "history": [
    { "role": "user", "content": "Hello" },
    { "role": "assistant", "content": "Hi! I can see your dataset..." }
  ],
  "stream": false
}
```

For streaming, set `"stream": true` — returns `text/event-stream` with SSE events:
```
data: {"text": "The highest..."}
data: {"text": " performing region..."}
data: [DONE]
```

---

## Agent Configuration

### POST /agent/configure
Save a custom agent config.
```json
{
  "agent_id": "sales",
  "name": "My Sales Agent",
  "system_prompt": "You are...",
  "extra_instructions": "Focus on overdue items only.",
  "dataset_ids": ["abc123"]
}
```

### GET /agent/config/{agent_id}
Load config (user override or default).

---

## Custom Agent Builder

### POST /agents/custom
Create a custom agent from the builder wizard.
```json
{
  "name": "CashFlow-Tracker",
  "description": "Tracks cashflow and flags overdue payments",
  "icon": "💰",
  "color": "#fbbf24",
  "sources": ["csv", "bank"],
  "actions": ["forecast", "flag", "analyse"],
  "outputs": ["chart", "table"],
  "share_destinations": ["slack", "email"],
  "infographic_style": ["timeline"],
  "extra_instructions": "Flag payments overdue > 30 days",
  "params": {
    "flag": ["Payment overdue > 30 days", "Balance < ₹0"],
    "analyse": ["Net cashflow", "Receivables", "Payables"]
  }
}
```

### GET /agents/custom
List all custom agents for current user.

### DELETE /agents/custom/{agent_id}
Delete a custom agent.

### POST /agents/generate-prompt
Preview the auto-generated system prompt before creating. Same body as POST /agents/custom.

---

## System

### GET /health
```json
{
  "status": "ok",
  "version": "2.0.0",
  "api_key_set": true,
  "datasets_in_memory": 3,
  "active_sessions": 1,
  "timestamp": "2024-01-15T10:30:00"
}
```
