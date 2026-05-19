from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from datetime import datetime, timezone

from ._utils import (
    call_deepseek,
    get_job_bundle,
    json_response,
    normalize_resume_text,
    read_json,
    supabase_request,
)


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        json_response(self, {"ok": True})

    def do_POST(self) -> None:
        try:
            payload = read_json(self)
            organization_id = payload.get("organization_id")
            job_id = payload.get("job_id")
            resumes = payload.get("resumes") or []
            if not organization_id:
                raise ValueError("organization_id 不能为空")
            if not job_id:
                raise ValueError("job_id 不能为空")
            if not resumes:
                raise ValueError("至少需要一份简历")

            job = get_job_bundle(job_id)
            task_rows = supabase_request(
                "POST",
                "screening_tasks",
                {
                    "organization_id": organization_id,
                    "job_id": job_id,
                    "status": "pending",
                    "resume_count": len(resumes),
                },
                prefer="return=representation",
            )
            task = task_rows[0]
            results = []

            for item in resumes:
                file_name = item.get("file_name") or item.get("resume_name") or item.get("resumeName") or "粘贴简历"
                parsed_text = normalize_resume_text(
                    file_name,
                    item.get("parsed_text") or item.get("resume_text") or item.get("resumeText") or "",
                )
                resume_rows = supabase_request(
                    "POST",
                    "resumes",
                    {
                        "organization_id": organization_id,
                        "candidate_name": item.get("candidate_name") or item.get("candidateName") or "未命名候选人",
                        "file_name": file_name,
                        "file_url": item.get("file_url"),
                        "parsed_text": parsed_text,
                        "source": item.get("source") or "manual",
                    },
                    prefer="return=representation",
                )
                resume = resume_rows[0]
                evaluation = call_deepseek(job, resume)
                result_rows = supabase_request(
                    "POST",
                    "screening_results",
                    {
                        "organization_id": organization_id,
                        "task_id": task["id"],
                        "resume_id": resume["id"],
                        "job_id": job_id,
                        "conclusion": evaluation["conclusion"],
                        "score": evaluation["score"],
                        "matched_points": evaluation["matched_points"],
                        "missing_points": evaluation["missing_points"],
                        "risk_points": evaluation["risk_points"],
                        "interview_questions": evaluation["interview_questions"],
                        "summary": evaluation["summary"],
                        "model_name": evaluation["model_name"],
                        "prompt_version": evaluation["prompt_version"],
                    },
                    prefer="return=representation",
                )
                results.append(result_rows[0])

            supabase_request(
                "PATCH",
                "screening_tasks",
                {"status": "completed", "completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds")},
                query={"id": f"eq.{task['id']}"},
            )
            json_response(self, {"task": task, "results": results}, status=201)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=400)
