# HireLens 简历筛选器

HireLens 是一个面向企业招聘场景的简历筛选原型，包含：

- 招聘岗位管理
- 结构化人才画像、硬性要求、加分项
- 简历评测流程
- 大模型优先的简历筛查后端
- SQLite 本地数据库

## 本地启动

```powershell
python resume_screener_backend/app.py
```

启动后访问：

```text
http://127.0.0.1:8765/
```

健康检查：

```text
http://127.0.0.1:8765/api/health
```

## 配置 DeepSeek

复制本地配置模板：

```powershell
Copy-Item resume_screener_backend/config.example.json resume_screener_backend/config.local.json
```

然后编辑：

```text
resume_screener_backend/config.local.json
```

填入：

```json
{
  "RESUME_SCREENER_LLM_PROVIDER": "deepseek",
  "RESUME_SCREENER_LLM_BASE_URL": "https://api.deepseek.com",
  "RESUME_SCREENER_MODEL": "deepseek-v4-flash",
  "RESUME_SCREENER_LLM_API_KEY": "你的 DeepSeek API Key",
  "RESUME_SCREENER_LLM_TIMEOUT": "60"
}
```

`config.local.json` 已加入 `.gitignore`，不要提交真实 API Key。

## Docker 部署

准备 `.env`：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，填入 DeepSeek Key，然后运行：

```powershell
docker compose up -d --build
```

访问：

```text
http://localhost:8765/
```

## 主要 API

- `GET /api/health`
- `GET /api/jobs`
- `POST /api/jobs`
- `PUT /api/jobs/{job_id}`
- `DELETE /api/jobs/{job_id}`
- `POST /api/resumes`
- `POST /api/screenings`
- `GET /api/results`
- `GET /api/results/{result_id}`

## 发布到 Git

建议只提交这些核心文件：

- `README.md`
- `.gitignore`
- `.env.example`
- `Dockerfile`
- `docker-compose.yml`
- `简历筛选器_MVP原型.html`
- `resume_screener_backend/app.py`
- `resume_screener_backend/model_client.py`
- `resume_screener_backend/run_backend.py`
- `resume_screener_backend/README.md`
- `resume_screener_backend/config.example.json`

不要提交：

- `resume_screener_backend/config.local.json`
- `resume_screener_backend/*.sqlite3`
- 日志文件
- Python 缓存
