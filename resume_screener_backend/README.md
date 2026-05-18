# HireLens 简历筛选后端

这是当前原型对应的最小可运行后端，使用 Python 标准库 + SQLite，不需要安装依赖。

评测策略现在是：

1. 优先调用大模型做语义筛查。
2. 如果没有配置 API Key，或模型接口失败，自动退回本地规则评分，保证业务链路不中断。

## 启动

```powershell
python resume_screener_backend/app.py
```

默认服务地址：

```text
http://127.0.0.1:8765
```

默认数据库：

```text
resume_screener_backend/resume_screener.sqlite3
```

## 配置大模型

后端使用 OpenAI-compatible Chat Completions 接口。OpenAI、DeepSeek、通义千问兼容接口、私有模型网关都可以按这个方式接入。

### DeepSeek 本地配置文件

复制：

```powershell
Copy-Item resume_screener_backend/config.example.json resume_screener_backend/config.local.json
```

然后把 `config.local.json` 里的 `RESUME_SCREENER_LLM_API_KEY` 替换成你的 DeepSeek API Key。

`config.local.json` 已加入 `.gitignore`，不会被提交到代码仓库。

默认 DeepSeek 配置：

```json
{
  "RESUME_SCREENER_LLM_PROVIDER": "deepseek",
  "RESUME_SCREENER_LLM_BASE_URL": "https://api.deepseek.com",
  "RESUME_SCREENER_MODEL": "deepseek-v4-flash"
}
```

PowerShell 示例：

```powershell
$env:RESUME_SCREENER_LLM_API_KEY="你的 API Key"
$env:RESUME_SCREENER_MODEL="gpt-4.1-mini"
$env:RESUME_SCREENER_LLM_BASE_URL="https://api.openai.com/v1"
python resume_screener_backend/app.py
```

如果使用兼容 OpenAI 的私有模型网关，只需要替换：

```powershell
$env:RESUME_SCREENER_LLM_BASE_URL="https://your-model-gateway.example.com/v1"
$env:RESUME_SCREENER_MODEL="your-resume-screening-model"
```

相关代码：

- `model_client.py`：构造 Prompt、调用大模型、解析 JSON
- `app.py`：`evaluate_resume()` 优先调用模型，失败后规则兜底

模型必须返回这个结构：

```json
{
  "conclusion": "非常匹配",
  "score": 86,
  "matched_points": ["..."],
  "missing_points": ["..."],
  "risk_points": ["..."],
  "interview_questions": ["..."],
  "summary": "..."
}
```

## 核心接口

### 健康检查

```http
GET /api/health
```

### 创建岗位

```http
POST /api/jobs
Content-Type: application/json
```

```json
{
  "title": "B2B 大客户销售经理",
  "headcount": 2,
  "arrival_date": "2026-06-30",
  "status": "在进行",
  "jd_text": "负责工业电子/元器件方向 B2B 客户开发，推进方案型销售、报价、合同和回款。",
  "persona": {
    "age_range": "28-38",
    "gender_preference": "不限",
    "work_years": "5 年以上",
    "min_education": "本科",
    "job_hop_frequency": "近 5 年不超过 2 次",
    "persona_keywords": ["大客户", "方案销售", "抗压", "回款"]
  },
  "must": {
    "years": "3 年以上 B2B 销售经验",
    "industry": "电子元器件、工业品或半导体",
    "skills": "大客户开发、方案销售、合同回款",
    "cert": "不限",
    "other": "能够独立推进销售线索到成交\n可接受华东区域出差"
  },
  "bonus": {
    "resources": "有华东制造业客户资源",
    "tools": "熟悉 CRM",
    "language": "英文邮件沟通",
    "management": "渠道或代理商管理",
    "other": "有技术型产品销售经验"
  }
}
```

### 岗位列表

```http
GET /api/jobs
```

### 更新岗位

```http
PUT /api/jobs/{job_id}
```

### 删除岗位

```http
DELETE /api/jobs/{job_id}
```

### 创建评测任务

```http
POST /api/screenings
Content-Type: application/json
```

```json
{
  "job_id": "job_xxx",
  "resumes": [
    {
      "candidate_name": "张三",
      "resume_name": "张三_销售经理简历.txt",
      "resume_text": "5 年 B2B 销售经验，负责华东区域大客户开发，熟悉电子元器件客户..."
    }
  ]
}
```

支持 BOSS 直聘下载的网页简历：

- `resume_name` / `file_name` 以 `.html` 或 `.htm` 结尾时，后端会自动去除 HTML 标签并提取正文。
- 即使文件名不是 HTML，只要内容明显是 HTML，后端也会自动清洗。
- 清洗后的正文存入 `resumes.parsed_text`，再进入大模型评测。

### 结果列表

```http
GET /api/results
GET /api/results?conclusion=非常匹配
GET /api/results?keyword=张三
GET /api/results?job_id=job_xxx
```

## 数据库表

- `jobs`：岗位基础信息
- `job_personas`：结构化人才画像
- `job_requirements`：硬性要求和加分项
- `resumes`：简历文本与候选人
- `screening_tasks`：评测任务
- `screening_results`：评测结论、分数、依据、风险点、面试追问

## 规则兜底

`score_resume()` 仍然保留，作用是：

- 本地开发时不配置模型也能跑通链路
- 模型接口失败时不影响 HR 上传和结果入库
- 后续可作为模型结果的审计参考
