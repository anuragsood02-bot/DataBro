# Deployment Guide

## Option 1: Render (Recommended — Free tier)

**Best for:** Quick demo, pitching to investors/clients, early users

### Steps

1. **Push this repo to GitHub**

2. **Go to [render.com](https://render.com)** → New → Web Service

3. **Connect your GitHub repo**

4. Render auto-detects `render.yaml`. Set one env var manually:
   - `ANTHROPIC_API_KEY` → your key from console.anthropic.com

5. **Deploy** — takes 2–3 minutes. You get:
   `https://databro-api.onrender.com`

6. **Update frontend**: Open `frontend/index.html`, find:
   ```js
   const BACKEND_URL = window.DATABRO_BACKEND_URL || 'http://localhost:8000';
   ```
   Change the fallback to your Render URL, or set `window.DATABRO_BACKEND_URL` on your hosting page.

7. **Host frontend** on Netlify (free):
   - Drag `frontend/` folder to [netlify.com/drop](https://netlify.com/drop)
   - You get `https://databro.netlify.app`

### Free tier caveats
- Spins down after 15 min idle → 30s cold start on first request
- No persistent disk (uploads lost on redeploy)
- Fix: upgrade to Render Starter ($7/mo) for always-on + persistent disk

---

## Option 2: Railway

Similar to Render. Supports `Procfile` (already included).

1. [railway.app](https://railway.app) → New Project → GitHub repo
2. Add env var: `ANTHROPIC_API_KEY`
3. Deploy

---

## Option 3: VPS (DigitalOcean / AWS / Hetzner)

**Best for:** Production SaaS with persistent storage

```bash
# 1. SSH into your VPS
ssh root@your-server-ip

# 2. Clone repo
git clone https://github.com/you/databro.git
cd databro

# 3. Install Python 3.11
apt update && apt install python3.11 python3.11-venv -y

# 4. Setup
cd backend
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
nano .env    # fill in ANTHROPIC_API_KEY and SECRET_KEY

# 5. Run with systemd (auto-restart on crash)
# See infra/databro.service

# 6. Nginx reverse proxy
# See infra/nginx.conf
```

---

## Option 4: Docker

```bash
# Build
docker build -t databro .

# Run
docker run -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e SECRET_KEY=your-secret \
  databro
```

---

## Custom Domain (GoDaddy / Namecheap)

1. Buy domain (e.g. `yourdatabro.com`)
2. In Render dashboard → your service → Settings → Custom Domain
3. Add `api.yourdatabro.com` → Render gives you a CNAME value
4. In GoDaddy DNS → Add CNAME record:
   - Host: `api`
   - Points to: `<value from Render>`
5. Wait 10–30 min for DNS propagation
6. Your API is live at `https://api.yourdatabro.com`

For frontend on Netlify:
- Netlify → Domain settings → Add custom domain → `app.yourdatabro.com`
- GoDaddy → Add CNAME: `app` → Netlify's value

---

## Environment Variables Checklist

| Variable | Required | Where to get |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ Yes | [console.anthropic.com](https://console.anthropic.com) |
| `SECRET_KEY` | ✅ Yes | Run: `openssl rand -hex 32` |
| `ENVIRONMENT` | Optional | Set to `production` |
| `ALLOWED_ORIGINS` | Optional | Your frontend domain |

---

## Production Checklist

- [ ] `ENVIRONMENT=production` (disables dev_token in magic links)
- [ ] `SECRET_KEY` is a strong random value (not the default)
- [ ] `ALLOWED_ORIGINS` set to your actual frontend URL
- [ ] `ANTHROPIC_API_KEY` is set and valid
- [ ] Remove `"dev_token"` from magic link response (already gated by `is_production`)
- [ ] Set up a persistent database (Postgres/Supabase) to replace in-memory stores
- [ ] Set up S3 or similar for file storage (replace local `uploads/` dir)
- [ ] Add rate limiting (fastapi-limiter or nginx)
- [ ] Set up error monitoring (Sentry)
