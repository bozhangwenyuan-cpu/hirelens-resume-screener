# HireLens Resume Screener

HireLens is a resume screening SaaS prototype for recruiting teams.

It supports:

- Job management
- Structured talent persona and screening criteria
- Resume upload, including BOSS Zhipin HTML resumes
- DeepSeek-powered resume screening
- Screening result management
- Vercel + Supabase SaaS deployment
- Local SQLite fallback for demos

## Recommended SaaS Architecture

```text
Vercel
  - Static web app
  - Serverless API routes under /api

Supabase
  - Auth
  - Postgres
  - Row Level Security
  - Optional resume file storage

DeepSeek
  - LLM screening engine
```

## Deploy With Vercel + Supabase

### 1. Create Supabase Project

Create a Supabase project, then open SQL Editor and run:

```text
supabase/schema.sql
```

This creates:

- organizations
- organization_members
- jobs
- job_personas
- job_requirements
- resumes
- screening_tasks
- screening_results

### 2. Configure Vercel Environment Variables

In Vercel project settings, add:

```text
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=your-supabase-anon-key
SUPABASE_SERVICE_ROLE_KEY=your-supabase-service-role-key
RESUME_SCREENER_LLM_PROVIDER=deepseek
RESUME_SCREENER_LLM_BASE_URL=https://api.deepseek.com
RESUME_SCREENER_MODEL=deepseek-v4-flash
RESUME_SCREENER_LLM_API_KEY=your-deepseek-api-key
RESUME_SCREENER_LLM_TIMEOUT=60
RESUME_SCREENER_VISION_TIMEOUT=90
RESUME_SCREENER_VISION_MAX_IMAGE_BYTES=358400
RESUME_SCREENER_VISION_MAX_TOKENS=1200

# Optional: use an OpenAI-compatible vision API to extract text from image resumes
RESUME_SCREENER_VISION_BASE_URL=https://api.openai.com/v1
RESUME_SCREENER_VISION_MODEL=gpt-4.1-mini
RESUME_SCREENER_VISION_API_KEY=your-openai-api-key
```

For Aliyun Bailian / DashScope vision extraction, use:

```text
RESUME_SCREENER_VISION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
RESUME_SCREENER_VISION_MODEL=qwen-vl-plus
RESUME_SCREENER_VISION_API_KEY=your-dashscope-api-key
```

Never commit real API keys.

### 3. Deploy

Import this GitHub repository into Vercel:

```text
https://github.com/bozhangwenyuan-cpu/hirelens-resume-screener
```

Vercel will serve:

- `/` -> web app
- `/api/health` -> health check
- `/api/jobs` -> SaaS job API backed by Supabase
- `/api/screenings` -> DeepSeek screening API backed by Supabase
- `/api/results` -> screening result API backed by Supabase

## Local Demo Mode

You can still run the original local SQLite backend:

```powershell
python resume_screener_backend/app.py
```

Then open:

```text
http://127.0.0.1:8765/
```

Local config:

```powershell
Copy-Item resume_screener_backend/config.example.json resume_screener_backend/config.local.json
```

Then edit `config.local.json` and add your DeepSeek API key.

## Docker Local Demo

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Local data is stored in:

```text
./data/resume_screener.sqlite3
```

## Security Notes

- `SUPABASE_SERVICE_ROLE_KEY` must only be used in Vercel serverless functions, never in browser code.
- Real DeepSeek keys must only be configured in Vercel environment variables or local ignored config files.
- `resume_screener_backend/config.local.json`, SQLite databases, logs, and `.env` are ignored by git.
- Age, gender, marriage, ethnicity, religion, health status, and other sensitive attributes must not affect automatic screening conclusions or scores.

## Current Status

This repository now contains two paths:

- `api/` + `supabase/`: online SaaS direction for Vercel + Supabase + DeepSeek
- `resume_screener_backend/`: local Python + SQLite demo backend
