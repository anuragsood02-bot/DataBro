# DataBro — Agentic AI Data Platform

> Upload your business data. Chat with it. Get insights in seconds.

DataBro is an **agentic AI SaaS platform** that turns CSV, Excel, and JSON files into intelligent business intelligence — no SQL, no dashboards, no data team required.

[![Deploy on Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy)

---

## What it does

- **Upload** CSV / Excel / JSON from any source (local, SharePoint, Google Sheets, bank exports)
- **Chat** with your data using natural language — Claude AI answers instantly
- **Analyse** with pre-built agents (Sales Planner, Finance Guardian, Inventory Auditor)
- **Build custom agents** with a 5-step wizard — define data sources, actions, output formats, infographics
- **Browse 12 templates** across Finance, Sales, Ops, HR and Marketing
- **Generate output** — tables, charts, PDF reports, infographics, CSV exports

---

## Architecture

```
databro/
├── backend/              # FastAPI Python backend
│   ├── api/              # Route handlers
│   ├── core/             # Config, auth, middleware
│   ├── models/           # Pydantic schemas
│   └── services/         # Business logic (Claude, file parsing)
├── frontend/             # Single-page app (HTML/CSS/JS)
├── infra/                # Deployment configs
└── docs/                 # API docs, setup guides
```

---

## Quick Start (Local)

```bash
# 1. Clone
git clone https://github.com/yourusername/databro.git
cd databro

# 2. Backend
cd backend
pip install -r requirements.txt
cp .env.example .env          # add your ANTHROPIC_API_KEY
uvicorn main:app --reload     # → http://localhost:8000

# 3. Frontend
# Open frontend/index.html in a browser
# Or serve it: npx serve frontend/
```

---

## Deploy to Render (Free)

1. Fork this repo
2. Go to [render.com](https://render.com) → New Web Service → connect your fork
3. Render auto-detects `render.yaml` — set `ANTHROPIC_API_KEY` in Environment
4. Deploy → get your `https://databro.onrender.com` URL
5. Update `BACKEND_URL` in `frontend/index.html`

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Your Claude API key from console.anthropic.com |
| `SECRET_KEY` | Yes | Random string for JWT signing (generate with `openssl rand -hex 32`) |
| `ENVIRONMENT` | No | `development` or `production` (default: development) |
| `ALLOWED_ORIGINS` | No | Comma-separated CORS origins (default: `*`) |
| `MAX_UPLOAD_MB` | No | Max file upload size in MB (default: 25) |
| `PORT` | No | Server port — injected by Render automatically |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Vanilla HTML/CSS/JS — zero dependencies, instant load |
| Backend | Python 3.11 + FastAPI |
| AI | Anthropic Claude (claude-sonnet-4-6) |
| Data | Pandas — CSV, Excel, JSON parsing |
| Auth | Magic-link email + JWT sessions |
| Deploy | Render (backend) + Netlify/Render static (frontend) |
| Storage | Local filesystem (demo) → S3 / Supabase (production) |

---

## Roadmap

- [ ] Persistent storage (PostgreSQL + S3)
- [ ] Email delivery via SendGrid / Resend
- [ ] Stripe billing integration
- [ ] Multi-tenant workspace support
- [ ] Slack / WhatsApp output delivery
- [ ] Google Sheets live connector
- [ ] SharePoint integration
- [ ] White-label / reseller mode

---

## License

MIT — free to use, modify, and build on.

---

Built with ❤️ using [Claude](https://anthropic.com) by Anthropic.
