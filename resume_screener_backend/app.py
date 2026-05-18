from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from model_client import PROMPT_VERSION, llm_enabled, screen_with_llm


ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(ROOT)
DB_PATH = os.environ.get("RESUME_SCREENER_DB", os.path.join(ROOT, "resume_screener.sqlite3"))
FRONTEND_PATH = os.environ.get(
    "RESUME_SCREENER_FRONTEND",
    os.path.join(PROJECT_ROOT, "简历筛选器_MVP原型.html"),
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None, fallback: Any = None) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY,
              title TEXT NOT NULL,
              headcount INTEGER NOT NULL DEFAULT 1,
              arrival_date TEXT,
              status TEXT NOT NULL CHECK(status IN ('停止','在进行','已完成')),
              jd_text TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS job_personas (
              job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
              age_range TEXT,
              gender_preference TEXT,
              work_years TEXT,
              min_education TEXT,
              job_hop_frequency TEXT,
              persona_keywords TEXT NOT NULL DEFAULT '[]',
              compliance_note TEXT
            );

            CREATE TABLE IF NOT EXISTS job_requirements (
              id TEXT PRIMARY KEY,
              job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
              type TEXT NOT NULL CHECK(type IN ('must','bonus')),
              field_key TEXT NOT NULL,
              field_label TEXT NOT NULL,
              field_value TEXT NOT NULL,
              weight REAL NOT NULL DEFAULT 1,
              is_knockout INTEGER NOT NULL DEFAULT 0,
              sort_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS resumes (
              id TEXT PRIMARY KEY,
              candidate_name TEXT NOT NULL,
              file_name TEXT,
              parsed_text TEXT NOT NULL,
              source TEXT NOT NULL DEFAULT 'manual',
              created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS screening_tasks (
              id TEXT PRIMARY KEY,
              job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
              status TEXT NOT NULL CHECK(status IN ('pending','completed','failed')),
              resume_count INTEGER NOT NULL DEFAULT 0,
              created_at TEXT NOT NULL,
              completed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS screening_results (
              id TEXT PRIMARY KEY,
              task_id TEXT NOT NULL REFERENCES screening_tasks(id) ON DELETE CASCADE,
              resume_id TEXT NOT NULL REFERENCES resumes(id) ON DELETE CASCADE,
              job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
              conclusion TEXT NOT NULL CHECK(conclusion IN ('非常匹配','一般匹配','不匹配')),
              score INTEGER NOT NULL,
              matched_points TEXT NOT NULL DEFAULT '[]',
              missing_points TEXT NOT NULL DEFAULT '[]',
              risk_points TEXT NOT NULL DEFAULT '[]',
              interview_questions TEXT NOT NULL DEFAULT '[]',
              model_name TEXT NOT NULL DEFAULT 'rules-v1',
              prompt_version TEXT NOT NULL DEFAULT 'screening-v1',
              review_status TEXT NOT NULL DEFAULT '待复核',
              created_at TEXT NOT NULL
            );
            """
        )


def split_items(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw = value
    else:
        raw = re.split(r"[\n,，、;；]+", str(value))
    return [str(item).strip() for item in raw if str(item).strip()]


def normalize_job_payload(payload: dict[str, Any], existing_id: str | None = None) -> dict[str, Any]:
    job_id = existing_id or payload.get("id") or new_id("job")
    persona = payload.get("persona") or {}
    must = payload.get("must") or payload.get("must_have") or {}
    bonus = payload.get("bonus") or payload.get("nice_have") or {}

    return {
        "job": {
            "id": job_id,
            "title": str(payload.get("title") or payload.get("name") or "").strip(),
            "headcount": int(payload.get("headcount") or 1),
            "arrival_date": payload.get("arrival_date") or payload.get("arrivalDate") or "",
            "status": payload.get("status") or "在进行",
            "jd_text": str(payload.get("jd_text") or payload.get("jd") or "").strip(),
        },
        "persona": {
            "age_range": persona.get("age_range") or persona.get("ageRange") or "",
            "gender_preference": persona.get("gender_preference") or persona.get("gender") or "不限",
            "work_years": persona.get("work_years") or persona.get("workYears") or "",
            "min_education": persona.get("min_education") or persona.get("education") or "不限",
            "job_hop_frequency": persona.get("job_hop_frequency") or persona.get("jobHopFreq") or "",
            "persona_keywords": split_items(persona.get("persona_keywords") or persona.get("keywords")),
            "compliance_note": persona.get("compliance_note") or "",
        },
        "requirements": build_requirements(job_id, must, bonus),
    }


def build_requirements(job_id: str, must: Any, bonus: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    def add(req_type: str, field_key: str, label: str, value: Any, order: int, knockout: bool = False) -> None:
        text = "；".join(split_items(value)) if isinstance(value, list) else str(value or "").strip()
        if not text or text == "不限":
            return
        rows.append(
            {
                "id": new_id("req"),
                "job_id": job_id,
                "type": req_type,
                "field_key": field_key,
                "field_label": label,
                "field_value": text,
                "weight": 1.0,
                "is_knockout": 1 if knockout else 0,
                "sort_order": order,
            }
        )

    if isinstance(must, dict):
        add("must", "years", "经验年限", must.get("years"), 10, True)
        add("must", "industry", "行业经验", must.get("industry"), 20, True)
        add("must", "skills", "核心技能", must.get("skills"), 30, True)
        add("must", "cert", "证书/资质", must.get("cert"), 40, False)
        for index, item in enumerate(split_items(must.get("other")), start=50):
            add("must", "other", "其他硬性要求", item, index, True)
    else:
        for index, item in enumerate(split_items(must), start=10):
            add("must", "other", "硬性要求", item, index, True)

    if isinstance(bonus, dict):
        add("bonus", "resources", "资源/客户", bonus.get("resources"), 10)
        add("bonus", "tools", "工具/系统", bonus.get("tools"), 20)
        add("bonus", "language", "语言能力", bonus.get("language"), 30)
        add("bonus", "management", "管理/协作", bonus.get("management"), 40)
        for index, item in enumerate(split_items(bonus.get("other")), start=50):
            add("bonus", "other", "其他加分项", item, index)
    else:
        for index, item in enumerate(split_items(bonus), start=10):
            add("bonus", "other", "加分项", item, index)

    return rows


def save_job(payload: dict[str, Any], existing_id: str | None = None) -> dict[str, Any]:
    data = normalize_job_payload(payload, existing_id)
    job = data["job"]
    if not job["title"] or not job["jd_text"]:
        raise ValueError("岗位名称和 JD 不能为空")
    if job["status"] not in {"停止", "在进行", "已完成"}:
        raise ValueError("岗位状态必须是：停止、在进行、已完成")
    if not any(row["type"] == "must" for row in data["requirements"]):
        raise ValueError("至少需要一个硬性要求")

    ts = now_iso()
    with connect() as conn:
        existed = conn.execute("SELECT id FROM jobs WHERE id=?", (job["id"],)).fetchone()
        if existed:
            conn.execute(
                """
                UPDATE jobs
                SET title=?, headcount=?, arrival_date=?, status=?, jd_text=?, updated_at=?
                WHERE id=?
                """,
                (job["title"], job["headcount"], job["arrival_date"], job["status"], job["jd_text"], ts, job["id"]),
            )
            conn.execute("DELETE FROM job_requirements WHERE job_id=?", (job["id"],))
        else:
            conn.execute(
                """
                INSERT INTO jobs (id,title,headcount,arrival_date,status,jd_text,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (job["id"], job["title"], job["headcount"], job["arrival_date"], job["status"], job["jd_text"], ts, ts),
            )

        persona = data["persona"]
        conn.execute(
            """
            INSERT INTO job_personas (
              job_id,age_range,gender_preference,work_years,min_education,job_hop_frequency,persona_keywords,compliance_note
            )
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(job_id) DO UPDATE SET
              age_range=excluded.age_range,
              gender_preference=excluded.gender_preference,
              work_years=excluded.work_years,
              min_education=excluded.min_education,
              job_hop_frequency=excluded.job_hop_frequency,
              persona_keywords=excluded.persona_keywords,
              compliance_note=excluded.compliance_note
            """,
            (
                job["id"],
                persona["age_range"],
                persona["gender_preference"],
                persona["work_years"],
                persona["min_education"],
                persona["job_hop_frequency"],
                json_dumps(persona["persona_keywords"]),
                persona["compliance_note"],
            ),
        )
        conn.executemany(
            """
            INSERT INTO job_requirements (
              id,job_id,type,field_key,field_label,field_value,weight,is_knockout,sort_order
            )
            VALUES (:id,:job_id,:type,:field_key,:field_label,:field_value,:weight,:is_knockout,:sort_order)
            """,
            data["requirements"],
        )
    return get_job(job["id"])


def row_to_job(row: sqlite3.Row, persona: sqlite3.Row | None, reqs: list[sqlite3.Row]) -> dict[str, Any]:
    requirements = [dict(req) for req in reqs]
    return {
        "id": row["id"],
        "title": row["title"],
        "headcount": row["headcount"],
        "arrival_date": row["arrival_date"],
        "status": row["status"],
        "jd_text": row["jd_text"],
        "persona": {
            "age_range": persona["age_range"] if persona else "",
            "gender_preference": persona["gender_preference"] if persona else "不限",
            "work_years": persona["work_years"] if persona else "",
            "min_education": persona["min_education"] if persona else "不限",
            "job_hop_frequency": persona["job_hop_frequency"] if persona else "",
            "persona_keywords": json_loads(persona["persona_keywords"], []) if persona else [],
            "compliance_note": persona["compliance_note"] if persona else "",
        },
        "requirements": requirements,
        "must_requirements": [req for req in requirements if req["type"] == "must"],
        "bonus_requirements": [req for req in requirements if req["type"] == "bonus"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_jobs() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM jobs ORDER BY updated_at DESC").fetchall()
    return [get_job(row["id"]) for row in rows]


def get_job(job_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError("岗位不存在")
        persona = conn.execute("SELECT * FROM job_personas WHERE job_id=?", (job_id,)).fetchone()
        reqs = conn.execute(
            "SELECT * FROM job_requirements WHERE job_id=? ORDER BY type DESC, sort_order ASC",
            (job_id,),
        ).fetchall()
    return row_to_job(row, persona, reqs)


def delete_job(job_id: str) -> None:
    with connect() as conn:
        cur = conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        if cur.rowcount == 0:
            raise KeyError("岗位不存在")


def html_to_text(raw: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg|canvas).*?>.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|section|article|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def looks_like_html(file_name: str, text: str) -> bool:
    lower_name = file_name.lower()
    return lower_name.endswith((".html", ".htm")) or bool(re.search(r"(?is)<html|<!doctype html|<body|<div|<p", text[:2000]))


def normalize_resume_text(file_name: str, raw_text: str) -> str:
    return html_to_text(raw_text) if looks_like_html(file_name, raw_text) else raw_text.strip()


def save_resume(candidate_name: str, file_name: str, parsed_text: str, source: str = "manual") -> dict[str, Any]:
    normalized_text = normalize_resume_text(file_name, parsed_text)
    if not normalized_text.strip():
        raise ValueError("简历文本不能为空")
    resume_id = new_id("resume")
    ts = now_iso()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO resumes (id,candidate_name,file_name,parsed_text,source,created_at)
            VALUES (?,?,?,?,?,?)
            """,
            (resume_id, candidate_name.strip() or "未命名候选人", file_name.strip(), normalized_text, source, ts),
        )
    return get_resume(resume_id)


def get_resume(resume_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM resumes WHERE id=?", (resume_id,)).fetchone()
    if not row:
        raise KeyError("简历不存在")
    return dict(row)


STOP_WORDS = {"以上", "以下", "经验", "能力", "负责", "能够", "熟悉", "相关", "之一", "岗位", "要求", "不限", "工作"}


def tokenize(text: str) -> list[str]:
    parts = re.split(r"[\s,，、/。；;:：()（）《》\[\]【】]+", text.lower())
    return [part.strip() for part in parts if len(part.strip()) >= 2 and part.strip() not in STOP_WORDS]


def is_matched(requirement: str, resume_text: str) -> bool:
    resume_lower = resume_text.lower()
    tokens = tokenize(requirement)
    if not tokens:
        return False
    return any(token in resume_lower for token in tokens)


def score_resume(job: dict[str, Any], resume: dict[str, Any]) -> dict[str, Any]:
    text = resume["parsed_text"]
    must = job["must_requirements"]
    bonus = job["bonus_requirements"]
    persona = job["persona"]

    matched_must = [req for req in must if is_matched(req["field_value"], text)]
    missing_must = [req for req in must if not is_matched(req["field_value"], text)]
    matched_bonus = [req for req in bonus if is_matched(req["field_value"], text)]
    missing_bonus = [req for req in bonus if not is_matched(req["field_value"], text)]
    jd_matches = [token for token in tokenize(job["jd_text"]) if token in text.lower()]
    persona_text = " ".join(
        [
            persona.get("age_range") or "",
            persona.get("work_years") or "",
            persona.get("min_education") or "",
            persona.get("job_hop_frequency") or "",
            " ".join(persona.get("persona_keywords") or []),
        ]
    )
    persona_matches = [token for token in tokenize(persona_text) if token in text.lower()]

    hard_score = (len(matched_must) / len(must) * 45) if must else 0
    jd_score = min(24, len(jd_matches) * 3)
    persona_score = min(19, len(persona_matches) * 2.2)
    bonus_score = (min(12, len(matched_bonus) / len(bonus) * 12) if bonus else 0)

    risk_points: list[str] = []
    risk_penalty = 0
    if re.search(r"频繁|跳槽|离职|空窗|gap|待业", text, re.I):
        risk_penalty += 8
        risk_points.append("简历中出现跳槽、离职或空窗相关表述，需要确认稳定性。")
    if not re.search(r"\d+\s*年|一年|两年|三年|四年|五年|多年", text):
        risk_penalty += 6
        risk_points.append("简历年限信息不够清晰，需要确认实际从业时间。")
    if must and len(missing_must) >= max(1, (len(must) + 1) // 2):
        risk_penalty += 12
        risk_points.append("硬性要求缺失较多，不建议直接进入面试。")

    score = round(max(0, min(100, hard_score + jd_score + persona_score + bonus_score - risk_penalty)))
    if score >= 75 and len(missing_must) <= 1:
        conclusion = "非常匹配"
    elif score >= 50 and matched_must:
        conclusion = "一般匹配"
    else:
        conclusion = "不匹配"

    matched_points = [f"硬性要求匹配：{req['field_label']} - {req['field_value']}" for req in matched_must]
    matched_points.extend([f"加分项匹配：{req['field_label']} - {req['field_value']}" for req in matched_bonus])
    missing_points = [f"硬性要求不明确：{req['field_label']} - {req['field_value']}" for req in missing_must]
    missing_points.extend([f"加分项未体现：{req['field_label']} - {req['field_value']}" for req in missing_bonus])

    return {
        "conclusion": conclusion,
        "score": score,
        "matched_points": matched_points or ["未识别到明确满足项，建议人工复核。"],
        "missing_points": missing_points or ["暂未发现关键缺失项。"],
        "risk_points": risk_points or ["暂无明显风险信号，但仍建议核实业绩真实性、离职原因和候选人动机。"],
        "interview_questions": [
            "请候选人举一个最典型项目，说明从线索到结果的完整过程。",
            "候选人过往核心业绩如何计算，个人贡献占比是多少？",
            "候选人对该岗位业务场景的理解是否具体？",
            *[f"重点追问硬性要求：{req['field_value']}" for req in missing_must[:3]],
        ],
        "model_name": "rules-v1",
        "prompt_version": "rules-v1",
    }


def evaluate_resume(job: dict[str, Any], resume: dict[str, Any]) -> dict[str, Any]:
    if not llm_enabled():
        return score_resume(job, resume)

    try:
        result = screen_with_llm(job, resume)
        result.setdefault("model_name", os.environ.get("RESUME_SCREENER_MODEL", "gpt-4.1-mini"))
        result.setdefault("prompt_version", PROMPT_VERSION)
        return result
    except Exception as exc:
        fallback = score_resume(job, resume)
        fallback["risk_points"] = [
            f"大模型评测失败，已使用规则评分兜底：{exc}",
            *fallback.get("risk_points", []),
        ]
        fallback["model_name"] = "rules-v1-fallback"
        fallback["prompt_version"] = "rules-v1"
        return fallback


def create_screening(job_id: str, resumes_payload: list[dict[str, Any]]) -> dict[str, Any]:
    if not resumes_payload:
        raise ValueError("至少需要一份简历")
    job = get_job(job_id)
    task_id = new_id("task")
    created_at = now_iso()
    results: list[dict[str, Any]] = []

    with connect() as conn:
        conn.execute(
            "INSERT INTO screening_tasks (id,job_id,status,resume_count,created_at) VALUES (?,?,?,?,?)",
            (task_id, job_id, "pending", len(resumes_payload), created_at),
        )

    for item in resumes_payload:
        resume = save_resume(
            candidate_name=item.get("candidate_name") or item.get("candidateName") or "未命名候选人",
            file_name=item.get("file_name") or item.get("resume_name") or item.get("resumeName") or "粘贴简历",
            parsed_text=item.get("parsed_text") or item.get("resume_text") or item.get("resumeText") or "",
            source=item.get("source") or "api",
        )
        evaluation = evaluate_resume(job, resume)
        result_id = new_id("result")
        ts = now_iso()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO screening_results (
                  id,task_id,resume_id,job_id,conclusion,score,matched_points,missing_points,
                  risk_points,interview_questions,model_name,prompt_version,created_at
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    result_id,
                    task_id,
                    resume["id"],
                    job_id,
                    evaluation["conclusion"],
                    evaluation["score"],
                    json_dumps(evaluation["matched_points"]),
                    json_dumps(evaluation["missing_points"]),
                    json_dumps(evaluation["risk_points"]),
                    json_dumps(evaluation["interview_questions"]),
                    evaluation.get("model_name", "rules-v1"),
                    evaluation.get("prompt_version", "rules-v1"),
                    ts,
                ),
            )
        results.append(get_result(result_id))

    with connect() as conn:
        conn.execute(
            "UPDATE screening_tasks SET status='completed', completed_at=? WHERE id=?",
            (now_iso(), task_id),
        )
    return {"task_id": task_id, "job": job, "results": results}


def get_result(result_id: str) -> dict[str, Any]:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT r.*, j.title AS job_title, cv.candidate_name, cv.file_name, cv.parsed_text
            FROM screening_results r
            JOIN jobs j ON j.id = r.job_id
            JOIN resumes cv ON cv.id = r.resume_id
            WHERE r.id=?
            """,
            (result_id,),
        ).fetchone()
    if not row:
        raise KeyError("评测结果不存在")
    return result_row_to_dict(row)


def list_results(query: dict[str, list[str]]) -> list[dict[str, Any]]:
    where: list[str] = []
    params: list[Any] = []
    if query.get("job_id"):
        where.append("r.job_id=?")
        params.append(query["job_id"][0])
    if query.get("conclusion"):
        where.append("r.conclusion=?")
        params.append(query["conclusion"][0])
    if query.get("keyword"):
        where.append("(cv.candidate_name LIKE ? OR cv.file_name LIKE ? OR j.title LIKE ?)")
        keyword = f"%{query['keyword'][0]}%"
        params.extend([keyword, keyword, keyword])
    sql = """
        SELECT r.*, j.title AS job_title, cv.candidate_name, cv.file_name, cv.parsed_text
        FROM screening_results r
        JOIN jobs j ON j.id = r.job_id
        JOIN resumes cv ON cv.id = r.resume_id
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.created_at DESC"
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [result_row_to_dict(row) for row in rows]


def result_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "resume_id": row["resume_id"],
        "job_id": row["job_id"],
        "job_title": row["job_title"],
        "candidate_name": row["candidate_name"],
        "file_name": row["file_name"],
        "conclusion": row["conclusion"],
        "score": row["score"],
        "matched_points": json_loads(row["matched_points"], []),
        "missing_points": json_loads(row["missing_points"], []),
        "risk_points": json_loads(row["risk_points"], []),
        "interview_questions": json_loads(row["interview_questions"], []),
        "model_name": row["model_name"],
        "prompt_version": row["prompt_version"],
        "review_status": row["review_status"],
        "created_at": row["created_at"],
    }


class ApiHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        self.send_json({"ok": True})

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            query = parse_qs(parsed.query)
            if path == "/" or path == "/app":
                self.send_frontend()
            elif path == "/api/health":
                self.send_json({"ok": True, "db_path": DB_PATH})
            elif path == "/api/jobs":
                self.send_json({"items": list_jobs()})
            elif path.startswith("/api/jobs/"):
                self.send_json(get_job(path.split("/")[-1]))
            elif path == "/api/results":
                self.send_json({"items": list_results(query)})
            elif path.startswith("/api/results/"):
                self.send_json(get_result(path.split("/")[-1]))
            else:
                self.send_error_json(404, "接口不存在")
        except KeyError as exc:
            self.send_error_json(404, str(exc))
        except Exception as exc:
            self.send_error_json(500, str(exc))

    def do_POST(self) -> None:
        try:
            path = (urlparse(self.path).path.rstrip("/") or "/")
            payload = self.read_json()
            if path == "/api/jobs":
                self.send_json(save_job(payload), status=201)
            elif path == "/api/resumes":
                self.send_json(
                    save_resume(
                        payload.get("candidate_name") or payload.get("candidateName") or "未命名候选人",
                        payload.get("file_name") or payload.get("resumeName") or "粘贴简历",
                        payload.get("parsed_text") or payload.get("resumeText") or "",
                        payload.get("source") or "api",
                    ),
                    status=201,
                )
            elif path == "/api/screenings":
                self.send_json(create_screening(payload.get("job_id") or payload.get("jobId"), payload.get("resumes") or []), status=201)
            else:
                self.send_error_json(404, "接口不存在")
        except (ValueError, TypeError) as exc:
            self.send_error_json(400, str(exc))
        except KeyError as exc:
            self.send_error_json(404, str(exc))
        except Exception as exc:
            self.send_error_json(500, str(exc))

    def do_PUT(self) -> None:
        try:
            path = urlparse(self.path).path.rstrip("/")
            if path.startswith("/api/jobs/"):
                self.send_json(save_job(self.read_json(), existing_id=path.split("/")[-1]))
            else:
                self.send_error_json(404, "接口不存在")
        except (ValueError, TypeError) as exc:
            self.send_error_json(400, str(exc))
        except KeyError as exc:
            self.send_error_json(404, str(exc))
        except Exception as exc:
            self.send_error_json(500, str(exc))

    def do_DELETE(self) -> None:
        try:
            path = urlparse(self.path).path.rstrip("/")
            if path.startswith("/api/jobs/"):
                delete_job(path.split("/")[-1])
                self.send_json({"ok": True})
            else:
                self.send_error_json(404, "接口不存在")
        except KeyError as exc:
            self.send_error_json(404, str(exc))
        except Exception as exc:
            self.send_error_json(500, str(exc))

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def send_json(self, data: Any, status: int = 200) -> None:
        body = json_dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json({"error": message}, status=status)

    def log_message(self, fmt: str, *args: Any) -> None:
        return

    def send_frontend(self) -> None:
        if not os.path.exists(FRONTEND_PATH):
            self.send_error_json(404, "前端页面不存在")
            return
        with open(FRONTEND_PATH, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    init_db()
    server = ThreadingHTTPServer((host, port), ApiHandler)
    print(f"Resume screener backend running at http://{host}:{port}")
    print(f"SQLite database: {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    run(
        host=os.environ.get("RESUME_SCREENER_HOST", "127.0.0.1"),
        port=int(os.environ.get("RESUME_SCREENER_PORT", "8765")),
    )
