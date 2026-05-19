from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from typing import Any


PROMPT_VERSION = "resume-screening-saas-v2"


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


def supabase_url(path: str, query: dict[str, str] | None = None) -> str:
    base = env("SUPABASE_URL").rstrip("/")
    url = f"{base}/rest/v1/{path.lstrip('/')}"
    if query:
        url += "?" + urllib.parse.urlencode(query)
    return url


def supabase_headers(prefer: str | None = None) -> dict[str, str]:
    key = env("SUPABASE_SERVICE_ROLE_KEY")
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
        data=json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None,
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


def normalize_resume_text(file_name: str, raw_text: str) -> str:
    lower = (file_name or "").lower()
    if lower.endswith((".html", ".htm")) or re.search(r"(?is)<html|<!doctype html|<body|<div|<p", raw_text[:2000]):
        return html_to_text(raw_text)
    return raw_text.strip()


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


def call_deepseek(job: dict[str, Any], resume: dict[str, Any]) -> dict[str, Any]:
    api_key = env("RESUME_SCREENER_LLM_API_KEY")
    if not api_key:
        raise RuntimeError("缺少 RESUME_SCREENER_LLM_API_KEY")

    base_url = env("RESUME_SCREENER_LLM_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = env("RESUME_SCREENER_MODEL", "deepseek-v4-flash")
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
    }


def ensure_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if value is None:
        return []
    return [str(value)]
