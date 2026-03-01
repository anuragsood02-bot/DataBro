# DataBro — Agentic AI Data Platform

> Upload your business data. Chat with it. Get insights in seconds. No SQL, no dashboards, no data team required.

[![Deploy on Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

---

## ⚡ What is DataBro?

DataBro is an **agentic AI SaaS platform** that turns CSV, Excel, and JSON files into intelligent business intelligence — powered by Anthropic Claude.

**Core capabilities:**
- Upload CSV / Excel / JSON from local, SharePoint, Google Sheets, bank exports
- Chat with your data in natural language — Claude answers instantly with real numbers
- Run pre-built agents: Sales Planner, Finance Guardian, Inventory Auditor
- Build fully custom agents using a 5-step wizard — no code required
- Browse 12 agent templates across Finance, Sales, Ops, HR, and Marketing
- Generate output: tables, charts, PDF reports, infographics, CSV exports

---

## 🗂️ Repository Structure

```
databro/
├── backend/
│   ├── main.py                  ← FastAPI app entry point — ALL routes live here
│   ├── core/
│   │   ├── config.py            ← Pydantic settings (reads .env)
│   │   └── auth.py              ← JWT session management, magic-link login
│   ├── models/
│   │   └── schemas.py           ← ALL Pydantic request/response models
│   ├── services/
│   │   ├── claude_service.py    ← All Anthropic API calls (chat, analysis, prompt gen)
│   │   └── file_service.py      ← File upload, parsing, schema inference, data context
│   └── requirements.txt
├── frontend/
│   └── index.html               ← Entire frontend — single HTML/CSS/JS file, zero deps
├── infra/
│   ├── nginx.conf
│   └── databro.service
├── docs/
│   ├── API.md
│   └── DEPLOYMENT.md
├── render.yaml                  ← Render deployment config
├── Dockerfile
└── README.md
```

**Important:** The entire frontend is a **single `index.html` file** — vanilla HTML/CSS/JS with zero npm dependencies. No React, no build step. Open it in a browser or serve it with `npx serve frontend/`.

---

## 🧠 AI & Agent Architecture

### Model
- **Model used:** `claude-sonnet-4-6` (set in `core/config.py` as `claude_model`)
- **Max tokens:** 4096 (configurable via `CLAUDE_MAX_TOKENS` env var)
- All Claude calls go through `backend/services/claude_service.py`

### Pre-built Agents (READ-ONLY — never editable by users)
Defined as hardcoded system prompts in `backend/main.py` in the `DEFAULT_PROMPTS` dict:

| Agent ID | Name | Purpose |
|---|---|---|
| `sales` | Sales Planner | Rep ranking, territory gaps, customer revenue breakdown |
| `finance` | Finance Guardian | Net cashflow, overdue vendors, inventory vs sales velocity |
| `inventory` | Inventory Auditor | Schema cross-matching, duplicates, data quality scoring |

These are **locked** — users cannot edit or delete them. They appear in the main agent selection UI.

### Custom Agents (User-built via 5-step wizard)
- Stored in memory: `CUSTOM_AGENTS: Dict[str, List[dict]]` (key = `user_id`)
- Also stored in browser `localStorage` as `databro_my_agents`
- Backend sync via `POST /agents/custom` and `PUT /agents/custom/{id}`
- Custom agents are prefixed `custom_` in their ID (e.g. `custom_a1b2c3d4`)
- Custom agents are completely separate from pre-built agents — they do not share config

### How Data Gets to Claude
1. User uploads file → `POST /upload` → saved to `uploads/` dir as `{user_id}_{dataset_id}.{ext}`
2. On chat/analysis: `file_service.build_data_context()` loads the file, builds aggregates + full row data as text
3. This context string is appended to the agent's system prompt before every Claude call
4. Claude sees: system prompt + column definitions + full CSV data (up to 300 rows) + user message

---

## 🛠️ Custom Agent Builder — 5-Step Wizard

This is the primary feature for user-created agents. All wizard state lives in the `BLD` JS object in `frontend/index.html`. The wizard flow:

### Step 1 — Identity
- Agent name (required)
- Description / goal
- Icon picker (emoji)
- Colour picker (accent colour)
- Live preview card

### Step 2 — Data Sources
- Source type chips: CSV/Excel upload, JSON, Google Sheets, SharePoint, OneDrive, Bank CSV, ERP Export, CRM Export, Live API
- File description rows: user describes each file and its columns (add/remove rows dynamically)
- **"Help the agent understand your data"** panel (optional but improves accuracy):
  - `bld-col-hints` — column meanings, e.g. `"Amount" = invoice value in INR. "Rep" is the sales rep, NOT the customer.`
  - `bld-understanding-notes` — data context, e.g. `Ignore rows where Status = "Draft"`
- Data cleaning options: dedup, nulls, type fix, trim, standardise

### Step 3 — Business Rules & SOPs
- `bld-rules-rows` — threshold/flag rules in plain English (add/remove rows)
- `bld-sop-rows` — standard operating procedures in plain English (add/remove rows)
- `bld-extra` — any additional AI instructions
- All rules are injected verbatim into the Claude system prompt with `RULE:` and `SOP:` prefixes

### Step 4 — Actions
- Action cards (multi-select): Analyse, Correlate, Flag Anomalies, Reconcile, Forecast, Rank, Deduplicate, Summarise
- `bld-params` — specific parameters e.g. `Correlate: Revenue vs Target. Flag: Amount > 50,000`
- **Action-level Business Rules** panel (optional):
  - `bld-action-rules-rows` — rules specific to the action step (add/remove rows)
  - `bld-action-extra` — additional action instructions

### Step 5 — Output & Infographics
- Output type cards: Data Table, Charts, PDF Report, Download CSV, Email Report, Chat Summary
- **Infographic preferences** panel:
  - Style chips: Auto, Executive Summary, Performance Heatmap, Trend Timeline, Funnel, Scorecard
  - `bld-infographic-notes` — what to show in charts, e.g. `Bar chart of variance by dept. Highlight top 5 in red.`
  - **Important:** Infographics are explicitly built from **output/analysis data — NOT raw input files**
- Delivery: Dashboard, Email, Slack, WhatsApp, Google Sheets, Download

### How the System Prompt is Generated
`bldBuildPrompt()` in `frontend/index.html` (JS) assembles the prompt client-side.
`generate_agent_prompt()` in `backend/services/claude_service.py` (Python) generates it server-side.
Both produce the same structured output — the JS version is used for immediate local save; the Python version is used when syncing to the backend.

The generated prompt has these sections (only included if user filled them in):
```
COLUMN DEFINITIONS & UNDERSTANDING
BUSINESS RULES (FOLLOW EXACTLY)
STANDARD OPERATING PROCEDURES
EXPECTED DATA FILES
YOUR TASKS
ACTION-SPECIFIC INSTRUCTIONS
OUTPUT & INFOGRAPHICS
ADDITIONAL INSTRUCTIONS
```

---

## 🌐 API Routes

All routes in `backend/main.py`. FastAPI docs at `/docs` when running locally.

### Auth
| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/login` | Magic-link login — email only, returns JWT token immediately |
| `POST` | `/auth/register` | Register with name + company |
| `POST` | `/auth/demo` | Instant demo login as `demo@databro.ai` |
| `GET` | `/auth/me` | Get current user from token |
| `POST` | `/auth/logout` | Invalidate session |

### Datasets
| Method | Path | Description |
|---|---|---|
| `POST` | `/upload` | Upload CSV/Excel/JSON — returns dataset ID + schema |
| `GET` | `/datasets` | List all datasets for current user |
| `DELETE` | `/datasets/{id}` | Delete dataset + file |
| `GET` | `/datasets/{id}/data` | Preview dataset rows (`?rows=100`) |

### Pre-built Agents
| Method | Path | Description |
|---|---|---|
| `POST` | `/agent/configure` | Save custom system prompt for a pre-built agent (per-user config) |
| `GET` | `/agent/config/{agent_id}` | Get agent config (falls back to default if not configured) |
| `POST` | `/agent/chat` | Chat with any agent — supports streaming (`stream: true`) |
| `POST` | `/agent/run` | Run full structured analysis — returns KPIs, insights, tables |

### Custom Agents (User-built)
| Method | Path | Description |
|---|---|---|
| `POST` | `/agents/custom` | Create new custom agent from wizard data |
| `PUT` | `/agents/custom/{id}` | Update existing custom agent (owner only) |
| `GET` | `/agents/custom` | List all custom agents for current user |
| `DELETE` | `/agents/custom/{id}` | Delete custom agent (owner only) |
| `POST` | `/agents/generate-prompt` | Preview auto-generated system prompt without saving |

### System
| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check — API key status, session count, dataset count |
| `GET` | `/correlate` | Find common columns across multiple datasets |

---

## 📋 Pydantic Schemas (backend/models/schemas.py)

Key schemas to know when working on the API:

### `CustomAgentCreate`
The main wizard payload. All fields are optional except `name`:
```python
name: str                          # Step 1 — required
description: str                   # Step 1
icon: str                          # Step 1
color: str                         # Step 1
sources: List[str]                 # Step 2 — e.g. ["csv", "gsheet"]
file_descriptions: List[str]       # Step 2 — user's file descriptions
clean: List[str]                   # Step 2 — cleaning options
column_metadata: str               # Step 2 — column definitions
understanding_notes: str           # Step 2 — additional data context
business_rules: List[str]          # Step 3 — plain-English rules
sops: List[str]                    # Step 3 — SOPs
extra_instructions: str            # Step 3 — other instructions
actions: List[str]                 # Step 4 — action type ids
action_parameters: str             # Step 4 — specific params to analyse
action_business_rules: List[str]   # Step 4 — action-level rules
action_extra: str                  # Step 4 — action instructions
outputs: List[str]                 # Step 5 — output format ids
infographic_style: List[str]       # Step 5 — chart style
infographic_notes: str             # Step 5 — what to show in charts
share_destinations: List[str]      # Step 5 — where to send output
params: Dict[str, List[str]]       # legacy field — kept for backwards compat
```

### `ChatRequest`
```python
agent_id: str
message: str
history: List[ChatMessage]   # last 20 messages sent to Claude
dataset_ids: List[str]       # which datasets to inject into context
stream: bool                 # true = SSE streaming response
```

---

## 🗄️ Data Storage (Current — In-Memory)

All data is stored in Python dicts in `main.py`. **Resets on server restart.** This is intentional for the demo/MVP phase.

```python
USER_DATASETS: Dict[str, List[dict]]    # user_id → list of dataset metadata
AGENT_CONFIGS: Dict[str, dict]          # f"{user_id}_{agent_id}" → config
CUSTOM_AGENTS: Dict[str, List[dict]]    # user_id → list of custom agents
SESSIONS: Dict[str, dict]               # token → session data (in core/auth.py)
```

Uploaded files are persisted to disk at `backend/uploads/{user_id}_{dataset_id}.{ext}`.

Custom agents are also saved to `localStorage` in the browser (`databro_my_agents`) so they survive server restarts.

**Production upgrade path:** Replace dicts with PostgreSQL + SQLAlchemy. Replace `localStorage` with DB-backed API.

---

## 🎨 Frontend Architecture (frontend/index.html)

Single file, ~2700 lines. Key sections:

### CSS Variables (`:root`)
```css
--ink, --ink2, --ink3, --ink4    /* dark backgrounds */
--border, --border2               /* border colours */
--volt, --volt2, --volt-dk        /* primary accent: lime green #b8ff57 */
--azure, --rose, --amber, --emerald, --purple, --orange
--mist, --fog                     /* text muted colours */
```

### Page/View System
Pages are `div.page` elements, shown/hidden by adding `.active` class. Main pages:
- `page-home` — landing page
- `page-auth` — login/register
- `page-dashboard` — main app with agent tabs
- `page-agent` — active agent chat view

### Global State Object
```javascript
const S = {
  sessionToken: null,    // JWT from /auth/login
  user: null,            // user object
  datasets: {},          // dataset_id → parsed dataset object
  currentAgent: null,    // active agent id
  myAgents: [],          // custom agents (also in localStorage)
  apiKey: null,          // optional direct Anthropic key
}
```

### Key JS Functions
```javascript
openAgent(id)            // switch to an agent and open chat
launchMyAgent(id)        // register custom agent + open it
openBuilder(prefill?)    // open 5-step wizard modal (prefill = edit mode)
bldNext()                // advance wizard step (async), save on step 5
bldSaveAgent()           // async: save to localStorage + POST to backend
useTpl(id)               // load template into builder and open it
renderMyAgents()         // re-render the "My Agents" grid
apiFetch(path, opts)     // authenticated fetch to BACKEND_URL
tryBackend(path, opts)   // apiFetch but never throws — returns null on error
toast(msg)               // show toast notification
```

### Backend URL
```javascript
const BACKEND_URL = 'http://localhost:8000';  // change for production
```
This constant is near the top of the `<script>` section. For Render deployment, update to `https://your-app.onrender.com`.

---

## 🏗️ Agent Templates Library

12 templates in the `TEMPLATES` array in `frontend/index.html`. Categories:

| Category | Templates |
|---|---|
| 💰 Finance (Highest ROI) | Finance-Guardian, CashFlow-Tracker, Expense-Auditor |
| 📈 Sales & CRM | Sales-Forecaster, Lead-Cleaner, Customer-Churn-Alert |
| 📦 Operations | Inventory-Replenisher, Delivery-Optimizer |
| 👥 HR | Payroll-Validator, Attrition-Risk-Monitor |
| 🎯 Marketing | Campaign-ROI-Analyser, Content-Performance-Tracker |

Each template has: `id, cat, icon, color, name, desc, srcs, actions, outputs, share, ig, rules, sops, fileDescs, colHints, tags`

Templates pre-fill the builder wizard — users can customise every field before saving.

### Finance Templates (Key Detail)

**Finance-Guardian**
- Data: P&L Excel, Budget Sheets, Bank CSV
- Actions: Reconcile, Flag, Analyse
- Rules: Flag variance >15%, flag duplicate payments (same vendor + amount within 30 days), >25% = CRITICAL
- Output: Monthly variance report + flagged items table → Email to finance head

**CashFlow-Tracker**
- Data: AR/AP Excel, Bank statements, Invoices
- Actions: Forecast, Flag, Analyse
- Rules: Flag overdue >30 days as HIGH RISK, >60 days as CRITICAL, alert when 30-day runway < 2x burn
- Output: Cashflow dashboard + overdue alerts → WhatsApp/Slack

**Expense-Auditor**
- Data: Expense receipts Excel, Approval logs, Budget sheet
- Actions: Flag, Analyse, Rank
- Rules: Meals >₹500 = policy violation, empty "Approved By" = unapproved spend, >30 days late = late submission
- Output: Expense summary + red-flagged items → Approval workflow

---

## ⚙️ Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | — | Claude API key from console.anthropic.com |
| `SECRET_KEY` | **Yes** | `change-me-in-production` | JWT signing key — `openssl rand -hex 32` |
| `ENVIRONMENT` | No | `development` | `development` or `production` |
| `ALLOWED_ORIGINS` | No | `*` | Comma-separated CORS origins |
| `MAX_UPLOAD_MB` | No | `25` | Max file upload size in MB |
| `PORT` | No | `8000` | Injected automatically by Render |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-6` | Claude model to use |
| `CLAUDE_MAX_TOKENS` | No | `4096` | Max tokens per Claude response |
| `SESSION_TTL_HOURS` | No | `72` | How long JWT sessions last |
| `UPLOAD_DIR` | No | `uploads` | Directory for uploaded files |
| `DEMO_MODE` | No | `true` | Enable demo login without email verify |
| `EMAIL_PROVIDER` | No | `none` | `none`, `resend`, `sendgrid`, or `smtp` |

---

## 🚀 Quick Start (Local)

```bash
# 1. Clone
git clone https://github.com/yourusername/databro.git
cd databro

# 2. Backend
cd backend
pip install -r requirements.txt
cp .env.example .env
# Edit .env — add ANTHROPIC_API_KEY and SECRET_KEY
uvicorn main:app --reload
# → API running at http://localhost:8000
# → Swagger docs at http://localhost:8000/docs

# 3. Frontend (new terminal)
# Open frontend/index.html directly in browser
# Or serve it:
npx serve frontend/
# → http://localhost:3000
```

---

## ☁️ Deploy to Render

1. Fork this repo
2. Go to [render.com](https://render.com) → New Web Service → connect your fork
3. Render auto-detects `render.yaml`
4. In Environment, add:
   - `ANTHROPIC_API_KEY` = your key
   - `SECRET_KEY` = `openssl rand -hex 32` output
5. Deploy → get your `https://databro.onrender.com` URL
6. In `frontend/index.html`, update `BACKEND_URL` to your Render URL
7. Deploy frontend to Netlify (drag-and-drop `frontend/index.html`) or Render Static Site

---

## 💻 Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | Vanilla HTML/CSS/JS | Zero dependencies, single file, instant load |
| Backend | Python 3.11 + FastAPI | All routes in `main.py` |
| AI | Anthropic Claude (`claude-sonnet-4-6`) | Via `services/claude_service.py` |
| Data parsing | Pandas | CSV, Excel (.xlsx/.xls), JSON |
| Auth | JWT sessions | Magic-link flow, in-memory sessions |
| Fonts | Cabinet Grotesk, Nacelle, JetBrains Mono | Google Fonts CDN |
| Charts | Chart.js 4.4.1 | CDN, used in frontend |
| CSV parsing | PapaParse 5.4.1 | CDN, used in frontend |
| Deploy | Render (backend) + Netlify (frontend) | Free tier works |
| Storage | Local filesystem + in-memory | → PostgreSQL + S3 for production |

---

## 🗺️ Roadmap

- [ ] PostgreSQL + SQLAlchemy (replace in-memory stores)
- [ ] S3 / Supabase file storage (replace local `uploads/` dir)
- [ ] Email delivery via SendGrid / Resend
- [ ] Stripe billing + subscription tiers
- [ ] Multi-tenant workspace support
- [ ] Slack / WhatsApp output delivery (currently UI-only)
- [ ] Google Sheets live connector (currently placeholder)
- [ ] SharePoint integration (currently placeholder)
- [ ] White-label / reseller mode
- [ ] Agent scheduling (run daily/weekly automatically)
- [ ] Output file download (PDF generation, CSV export from analysis results)
- [ ] Agent run history + audit log

---

## 🤖 Working with Claude on this project

When starting a new session with Claude, share this README and say:

> *"This is the DataBro project. Read the README for full context. I want to work on [specific feature]."*

Then paste in the specific file(s) you want to change.

### Key things Claude must know to help effectively

1. **Frontend is one file** — `frontend/index.html` — all HTML, CSS, and JS in one place, ~2700 lines
2. **All backend routes are in `main.py`** — not split into separate route files
3. **Custom agents ≠ pre-built agents** — pre-built (`sales`, `finance`, `inventory`) are hardcoded in `DEFAULT_PROMPTS` in `main.py` and must **never** be editable by users. Custom agents always have IDs prefixed `custom_`
4. **`BLD` object** — the wizard state in frontend JS; `bldCollectStep(n)` reads the DOM into it, `bldSaveAgent()` is async and POSTs to `/agents/custom`
5. **`S` object** — global app state in frontend JS; `S.myAgents` = user's custom agents (synced with `localStorage`)
6. **Templates pre-fill the builder** — `useTpl(id)` calls `openBuilder(prefillData)` with template data
7. **Infographics = output-based** — a core product decision: charts/infographics are built from analysis results (output data), NOT raw input files. This is enforced in both the UI copy and the generated system prompt
8. **`tryBackend()`** — never throws, returns null on failure; used for all backend calls from frontend so the app degrades gracefully in offline/demo mode
9. **In-memory storage** — `USER_DATASETS`, `CUSTOM_AGENTS`, `AGENT_CONFIGS` in `main.py` are Python dicts that reset on server restart. `localStorage` in the browser is the persistence fallback
10. **Wizard HTML element IDs** — each step has specific IDs: `bld-col-hints`, `bld-understanding-notes`, `bld-rules-rows`, `bld-sop-rows`, `bld-action-rules-rows`, `bld-action-extra`, `bld-ig-group`, `bld-share-group`, `bld-infographic-notes`

### Files to share with Claude when asking for help

| Task | Files to share |
|---|---|
| Backend routes / API changes | `backend/main.py` + `backend/models/schemas.py` |
| AI prompt / Claude behaviour | `backend/services/claude_service.py` |
| File upload / data parsing | `backend/services/file_service.py` |
| Frontend UI / wizard changes | `frontend/index.html` (or the relevant section) |
| Config / env vars | `backend/core/config.py` |
| Auth changes | `backend/core/auth.py` |

---

## 📄 License

MIT — free to use, modify, and build on.

---

Built with ❤️ using [Claude](https://anthropic.com) by Anthropic.
