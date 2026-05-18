from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any


ROOT = os.path.dirname(os.path.abspath(__file__))
LOCAL_CONFIG_PATH = os.environ.get("RESUME_SCREENER_CONFIG", os.path.join(ROOT, "config.local.json"))
LOCAL_CONFIG = {}
if os.path.exists(LOCAL_CONFIG_PATH):
    with open(LOCAL_CONFIG_PATH, "r", encoding="utf-8") as f:
        LOCAL_CONFIG = json.load(f)


def config_value(name: str, default: str = "") -> str:
    return os.environ.get(name) or str(LOCAL_CONFIG.get(name) or default)


DEFAULT_MODEL = config_value("RESUME_SCREENER_MODEL", "gpt-4.1-mini")
DEFAULT_BASE_URL = config_value("RESUME_SCREENER_LLM_BASE_URL", "https://api.openai.com/v1")
DEFAULT_PROVIDER = config_value("RESUME_SCREENER_LLM_PROVIDER", "openai-compatible")
PROMPT_VERSION = "resume-screening-llm-v2"


SYSTEM_PROMPT = """你是企业招聘简历初筛专家。你的任务是根据岗位 JD、结构化人才画像、硬性要求和加分项评估候选人简历。

必须遵守：
1. 只基于输入信息判断，不要虚构简历中没有的经历。
2. 硬性要求权重最高；关键硬性要求明显不满足时，不得评为“非常匹配”。
3. 年龄、性别、婚育、民族、宗教、健康状况等敏感信息不得影响 conclusion 和 score。
4. 如果岗位画像里包含年龄或性别，只能把“信息未提供/需人工合规复核”写入 risk_points，不得作为淘汰或降分依据。
5. 要区分“明确不满足”和“简历未体现”：未体现的信息写入 missing_points，不要直接推定候选人不具备。
6. 输出必须是合法 JSON，不要输出 Markdown，不要输出额外解释。
7. conclusion 只能是：非常匹配、一般匹配、不匹配。
"""


def llm_enabled() -> bool:
    return bool(config_value("RESUME_SCREENER_LLM_API_KEY"))


def build_screening_prompt(job: dict[str, Any], resume: dict[str, Any]) -> dict[str, Any]:
    return {
        "task": "resume_screening",
        "output_schema": {
            "conclusion": "非常匹配 / 一般匹配 / 不匹配",
            "score": "0-100 integer",
            "matched_points": ["明确匹配点，必须引用岗位要求或简历事实"],
            "missing_points": ["缺失、不明确或需要补充的信息"],
            "risk_points": ["需要人工复核的风险点"],
            "interview_questions": ["建议面试追问"],
            "summary": "不超过 120 字的结论摘要",
        },
        "scoring_guidance": {
            "hard_requirements": "45%",
            "jd_experience_match": "25%",
            "persona_match": "15%",
            "bonus_points": "10%",
            "risk_control": "5%",
            "compliance_rule": "年龄、性别等敏感字段不得计入分数，只能作为人工复核提示。",
        },
        "job": job,
        "resume": {
            "id": resume.get("id"),
            "candidate_name": resume.get("candidate_name"),
            "file_name": resume.get("file_name"),
            "parsed_text": resume.get("parsed_text"),
        },
    }


def screen_with_llm(job: dict[str, Any], resume: dict[str, Any]) -> dict[str, Any]:
    api_key = config_value("RESUME_SCREENER_LLM_API_KEY")
    if not api_key:
        raise RuntimeError("未配置 RESUME_SCREENER_LLM_API_KEY")

    model = config_value("RESUME_SCREENER_MODEL", DEFAULT_MODEL)
    base_url = config_value("RESUME_SCREENER_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    url = f"{base_url}/chat/completions"
    prompt_payload = build_screening_prompt(job, resume)

    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(prompt_payload, ensure_ascii=False)},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=int(config_value("RESUME_SCREENER_LLM_TIMEOUT", "60"))) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"大模型接口返回错误：HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"大模型接口连接失败：{exc.reason}") from exc

    data = json.loads(raw)
    content = data["choices"][0]["message"]["content"]
    parsed = parse_json_content(content)
    return normalize_llm_result(parsed, model)


def parse_json_content(content: str) -> dict[str, Any]:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", content)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_llm_result(data: dict[str, Any], model: str) -> dict[str, Any]:
    conclusion = data.get("conclusion")
    if conclusion not in {"非常匹配", "一般匹配", "不匹配"}:
        conclusion = "一般匹配"

    try:
        score = int(data.get("score", 0))
    except (TypeError, ValueError):
        score = 0
    score = max(0, min(100, score))

    return {
        "conclusion": conclusion,
        "score": score,
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
