from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import socket
from base64 import b64decode
from html import unescape
from io import BytesIO
from typing import Any


PROMPT_VERSION = "resume-screening-saas-v3"


SKILL_PROMPTS = {
    "balanced": "采用均衡筛选方法：硬性要求、职责匹配、稳定性风险和加分项都要纳入，适合大多数岗位初筛。",
    "strict": "采用强硬性要求筛选方法：只要关键硬性要求缺失或无法证明，就明显降低分数；不确定时倾向人工复核或不匹配。",
    "potential": "采用潜力识别方法：允许候选人部分经历不完全对口，但要重点寻找迁移能力、学习能力、复杂项目经验和成长曲线。",
    "sales": "采用销售岗位筛选方法：重点检查客户开发、业绩数字、客单价、销售周期、回款、行业资源、抗压和稳定性。",
    "product": "采用产品岗位筛选方法：重点检查需求分析、PRD/原型、项目推进、数据/AI理解、跨部门协作和业务抽象能力。",
}


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def json_response(handler: Any, data: Any, status: int = 200) -> None:
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET,POST,PATCH,DELETE,OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type,Authorization")
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler: Any) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def clean_text_value(value: str) -> str:
    return value.replace("\x00", "").replace("\\u0000", "")


def sanitize_for_database(value: Any) -> Any:
    if isinstance(value, str):
        return clean_text_value(value)
    if isinstance(value, list):
        return [sanitize_for_database(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_for_database(item) for key, item in value.items()}
    return value


def supabase_url(path: str, query: dict[str, str] | None = None) -> str:
    base = env("SUPABASE_URL").rstrip("/")
    if not base:
        raise RuntimeError("缺少 Vercel 环境变量 SUPABASE_URL，请在 Vercel Project Settings -> Environment Variables 中配置 Supabase Project URL 后重新部署。")
    if not base.startswith(("http://", "https://")):
        raise RuntimeError("SUPABASE_URL 格式不正确，必须类似 https://xxxx.supabase.co")
    url = f"{base}/rest/v1/{path.lstrip('/')}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return url


def supabase_headers(prefer: str | None = None) -> dict[str, str]:
    key = env("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise RuntimeError("缺少 Vercel 环境变量 SUPABASE_SERVICE_ROLE_KEY，请在 Vercel Project Settings -> Environment Variables 中配置 Supabase Secret/Service Role Key 后重新部署。")
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


def supabase_request(method: str, path: str, data: Any | None = None, query: dict[str, str] | None = None, prefer: str | None = None) -> Any:
    req = urllib.request.Request(
        supabase_url(path, query),
        data=json.dumps(sanitize_for_database(data), ensure_ascii=False).encode("utf-8") if data is not None else None,
        headers=supabase_headers(prefer),
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Supabase error {exc.code}: {detail}") from exc


def html_to_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg|canvas).*?>.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|section|article|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def pdf_to_text(file_name: str, file_base64: str) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("服务端缺少 PDF 解析依赖 pypdf，请重新部署后再上传 PDF 简历。") from exc

    try:
        reader = PdfReader(BytesIO(b64decode(file_base64)))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as exc:
        raise RuntimeError(f"{file_name} 解析失败，请确认文件是可读取的 PDF。") from exc

    text = clean_text_value("\n\n".join(page for page in pages if page).strip())
    if len(text) < 80:
        raise RuntimeError(f"{file_name} 未提取到有效文本，可能是扫描件或图片型 PDF。请上传可复制文字的 PDF、HTML 简历，或复制简历正文粘贴评测。")
    return text


def image_to_text(file_name: str, file_base64: str, mime_type: str, skill: dict[str, Any] | None = None) -> str:
    api_key = env("RESUME_SCREENER_VISION_API_KEY") or env("OPENAI_API_KEY") or env("RESUME_SCREENER_LLM_API_KEY")
    if not api_key:
        raise RuntimeError("缺少图片解析 API Key。请配置 RESUME_SCREENER_VISION_API_KEY 或 OPENAI_API_KEY。")
    model = env("RESUME_SCREENER_VISION_MODEL", "").strip()
    if not model:
        raise RuntimeError(f"{file_name} 是图片文件。当前部署尚未配置图片解析模型 RESUME_SCREENER_VISION_MODEL，请配置支持图片识别的视觉模型，或先上传 PDF/HTML/文本简历。")
    image_bytes = int(len(file_base64) * 0.75)
    max_image_bytes = int(env("RESUME_SCREENER_VISION_MAX_IMAGE_BYTES", str(350 * 1024)))
    if image_bytes > max_image_bytes:
        raise RuntimeError(f"{file_name} 图片压缩后仍有 {round(image_bytes / 1024)}KB，超过当前限制 {round(max_image_bytes / 1024)}KB。请截图更小区域，或上传 HTML/PDF 简历。")

    base_url = env("RESUME_SCREENER_VISION_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": int(env("RESUME_SCREENER_VISION_MAX_TOKENS", "1200")),
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "你是简历图片 OCR 助手。请只抽取招聘初筛需要的关键信息，不要逐字完整转写。"
                            "输出纯文本，控制在 1500 字以内，按以下字段组织：候选人姓名、当前/最近岗位、工作年限、教育经历、"
                            "核心经历、项目/业绩、技能工具、行业经验、证书语言、稳定性线索、其他可评测信息。"
                            "如果图片中某项看不清，写“不清晰”。不要评价候选人，不要输出 Markdown 表格。"
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type or 'image/png'};base64,{file_base64}"}},
                ],
            }
        ],
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(env("RESUME_SCREENER_VISION_TIMEOUT", env("RESUME_SCREENER_LLM_TIMEOUT", "60")))) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"图片解析模型调用失败 {exc.code}: {detail}") from exc
    except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        raise RuntimeError("图片解析超时。请稍后重试，或上传更清晰但体积更小的图片/HTML/PDF 简历。") from exc
    text = clean_text_value(raw["choices"][0]["message"]["content"].strip())
    if len(text) < 50:
        raise RuntimeError(f"{file_name} 未提取到有效简历文本，请确认图片清晰，或改用文本/PDF/HTML 简历。")
    return text


def normalize_resume_text(file_name: str, raw_text: str, file_base64: str = "", mime_type: str = "", skill: dict[str, Any] | None = None) -> str:
    lower = (file_name or "").lower()
    if lower.endswith(".pdf") and file_base64:
        return pdf_to_text(file_name, file_base64)
    if (mime_type or "").startswith("image/") or lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".bmp")):
        if not file_base64:
            raise RuntimeError(f"{file_name} 是图片文件，但没有收到图片内容。")
        return image_to_text(file_name, file_base64, mime_type, skill)
    if lower.endswith((".html", ".htm")) or re.search(r"(?is)<html|<!doctype html|<body|<div|<p", raw_text[:2000]):
        return clean_text_value(html_to_text(raw_text))
    return clean_text_value(raw_text.strip())


def get_job_bundle(job_id: str) -> dict[str, Any]:
    jobs = supabase_request("GET", "jobs", query={"id": f"eq.{job_id}", "select": "*"})
    if not jobs:
        raise ValueError("岗位不存在")
    job = jobs[0]
    personas = supabase_request("GET", "job_personas", query={"job_id": f"eq.{job_id}", "select": "*"})
    reqs = supabase_request("GET", "job_requirements", query={"job_id": f"eq.{job_id}", "select": "*", "order": "sort_order.asc"})
    job["persona"] = personas[0] if personas else {}
    job["requirements"] = reqs or []
    job["must_requirements"] = [row for row in job["requirements"] if row.get("type") == "must"]
    job["bonus_requirements"] = [row for row in job["requirements"] if row.get("type") == "bonus"]
    return job


def normalize_skill(skill: Any) -> dict[str, str]:
    if not isinstance(skill, dict):
        skill = {}
    skill_id = str(skill.get("id") or skill.get("skill_id") or "balanced")
    custom = str(skill.get("custom") or skill.get("custom_prompt") or "").strip()
    return {
        "id": skill_id,
        "name": str(skill.get("name") or skill_id),
        "instruction": custom or SKILL_PROMPTS.get(skill_id, SKILL_PROMPTS["balanced"]),
    }


def call_deepseek(job: dict[str, Any], resume: dict[str, Any], skill: Any = None) -> dict[str, Any]:
    api_key = env("RESUME_SCREENER_LLM_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 RESUME_SCREENER_LLM_API_KEY")

    base_url = env("RESUME_SCREENER_LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = env("RESUME_SCREENER_MODEL", "deepseek-v4-flash")
    evaluation_skill = normalize_skill(skill)
    payload = {
        "model": model,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是企业招聘简历初筛专家，目标是帮助 HR 做稳定、可复核的一面前初筛。"
                    "必须逐条检查岗位硬性要求、人才画像、加分项，并引用简历中的具体证据或说明缺失原因。"
                    "只基于输入信息判断，不要虚构；没有证据时必须写“不明确”或“未体现”。"
                    "年龄、性别、婚育、民族、宗教、健康状况等敏感信息不得影响 conclusion 和 score，只能作为人工复核风险提示。"
                    "评分规则：硬性要求占 60%，JD 职责匹配占 20%，加分项占 10%，风险扣分占 10%。"
                    "如果关键硬性要求缺失 2 项及以上，不能给“非常匹配”。如果核心硬性要求完全不明确，优先给“不匹配”。"
                    "必须遵循本次传入的 screening_skill 来调整检查重点、扣分严格度和追问方向。"
                    "输出合法 JSON，conclusion 只能是：非常匹配、一般匹配、不匹配。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "resume_screening",
                        "output_schema": {
                            "conclusion": "非常匹配 / 一般匹配 / 不匹配",
                            "score": "0-100 integer",
                            "matched_points": ["每条都要包含：要求/证据/判断"],
                            "missing_points": ["每条都要包含：要求/缺失原因/影响"],
                            "risk_points": ["每条都要包含：风险/原因/建议核实方式"],
                            "interview_questions": ["围绕缺失项、风险项和关键业绩设计 3-6 个追问"],
                            "summary": "用 2-4 句话说明整体判断逻辑，不要空泛",
                        },
                        "screening_skill": evaluation_skill,
                        "job": job,
                        "resume": resume,
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    }
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(env("RESUME_SCREENER_LLM_TIMEOUT", "60"))) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"DeepSeek error {exc.code}: {detail}") from exc
    content = raw["choices"][0]["message"]["content"]
    data = json.loads(content)
    conclusion = data.get("conclusion") if data.get("conclusion") in {"非常匹配", "一般匹配", "不匹配"} else "一般匹配"
    return {
        "conclusion": conclusion,
        "score": max(0, min(100, int(data.get("score", 0)))),
        "matched_points": ensure_list(data.get("matched_points")),
        "missing_points": ensure_list(data.get("missing_points")),
        "risk_points": ensure_list(data.get("risk_points")),
        "interview_questions": ensure_list(data.get("interview_questions")),
        "summary": str(data.get("summary") or ""),
        "model_name": model,
        "prompt_version": PROMPT_VERSION,
        "skill_id": evaluation_skill["id"],
    }


def ensure_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None:
        return []
    return [str(value)]
