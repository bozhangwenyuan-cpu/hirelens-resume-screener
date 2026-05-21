from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ._utils import json_response, read_json, supabase_request


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        json_response(self, {"ok": True})

    def do_GET(self) -> None:
        try:
            query = parse_qs(urlparse(self.path).query)
            organization_id = (query.get("organization_id") or [""])[0]
            if not organization_id:
                raise ValueError("organization_id 不能为空")
            jobs = supabase_request(
                "GET",
                "jobs",
                query={
                    "organization_id": f"eq.{organization_id}",
                    "select": "*,job_personas(*),job_requirements(*)",
                    "order": "updated_at.desc",
                },
            )
            json_response(self, {"items": jobs or []})
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=400)

    def do_PATCH(self) -> None:
        try:
            payload = read_json(self)
            organization_id = payload.get("organization_id")
            job_id = payload.get("id") or payload.get("job_id")
            if not organization_id:
                raise ValueError("organization_id 不能为空")
            if not job_id:
                raise ValueError("job_id 不能为空")

            job_rows = supabase_request(
                "PATCH",
                "jobs",
                {
                    "title": payload.get("title") or payload.get("name"),
                    "headcount": payload.get("headcount") or 1,
                    "arrival_date": payload.get("arrival_date") or payload.get("arrivalDate") or None,
                    "status": payload.get("status") or "在进行",
                    "jd_text": payload.get("jd_text") or payload.get("jd") or "",
                },
                query={"id": f"eq.{job_id}", "organization_id": f"eq.{organization_id}"},
                prefer="return=representation",
            )
            if not job_rows:
                raise ValueError("岗位不存在")
            job = job_rows[0]

            persona = payload.get("persona") or {}
            supabase_request(
                "PATCH",
                "job_personas",
                {
                    "age_range": persona.get("age_range") or persona.get("ageRange"),
                    "gender_preference": persona.get("gender_preference") or persona.get("gender") or "不限",
                    "work_years": persona.get("work_years") or persona.get("workYears"),
                    "min_education": persona.get("min_education") or persona.get("education") or "不限",
                    "job_hop_frequency": persona.get("job_hop_frequency") or persona.get("jobHopFreq"),
                    "persona_keywords": persona.get("persona_keywords") or persona.get("keywords") or [],
                },
                query={"job_id": f"eq.{job_id}"},
            )
            requirements = self._clean_requirements(payload.get("requirements") or [])
            supabase_request("DELETE", "job_requirements", query={"job_id": f"eq.{job_id}"})
            self._insert_requirements(job_id, requirements)
            json_response(self, job)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=400)

    def do_POST(self) -> None:
        try:
            payload = read_json(self)
            organization_id = payload.get("organization_id")
            if not organization_id:
                raise ValueError("organization_id 不能为空")
            job_rows = supabase_request(
                "POST",
                "jobs",
                {
                    "organization_id": organization_id,
                    "title": payload.get("title") or payload.get("name"),
                    "headcount": payload.get("headcount") or 1,
                    "arrival_date": payload.get("arrival_date") or payload.get("arrivalDate") or None,
                    "status": payload.get("status") or "在进行",
                    "jd_text": payload.get("jd_text") or payload.get("jd") or "",
                },
                prefer="return=representation",
            )
            job = job_rows[0]
            persona = payload.get("persona") or {}
            supabase_request(
                "POST",
                "job_personas",
                {
                    "job_id": job["id"],
                    "age_range": persona.get("age_range") or persona.get("ageRange"),
                    "gender_preference": persona.get("gender_preference") or persona.get("gender") or "不限",
                    "work_years": persona.get("work_years") or persona.get("workYears"),
                    "min_education": persona.get("min_education") or persona.get("education") or "不限",
                    "job_hop_frequency": persona.get("job_hop_frequency") or persona.get("jobHopFreq"),
                    "persona_keywords": persona.get("persona_keywords") or persona.get("keywords") or [],
                },
                prefer="return=representation",
            )
            self._insert_requirements(job["id"], self._clean_requirements(payload.get("requirements") or []))
            json_response(self, job, status=201)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=400)

    def do_DELETE(self) -> None:
        try:
            params = parse_qs(urlparse(self.path).query)
            organization_id = (params.get("organization_id") or [""])[0]
            job_id = (params.get("id") or [""])[0]
            if not organization_id:
                raise ValueError("organization_id 不能为空")
            if not job_id:
                raise ValueError("id 不能为空")
            supabase_request(
                "DELETE",
                "jobs",
                query={"id": f"eq.{job_id}", "organization_id": f"eq.{organization_id}"},
            )
            json_response(self, {"ok": True})
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=400)

    def _insert_requirements(self, job_id: str, requirements: list[dict]) -> None:
        if not requirements:
            return
        rows = []
        for index, req in enumerate(requirements):
            rows.append(
                {
                    "job_id": job_id,
                    "type": req.get("type", "must"),
                    "field_key": req.get("field_key") or req.get("key") or "other",
                    "field_label": req.get("field_label") or req.get("label") or "要求",
                    "field_value": req.get("field_value") or req.get("value") or "",
                    "weight": req.get("weight") or 1,
                    "is_knockout": bool(req.get("is_knockout") or req.get("isKnockout")),
                    "sort_order": req.get("sort_order") or index,
                }
            )
        supabase_request("POST", "job_requirements", rows, prefer="return=representation")

    def _clean_requirements(self, requirements: list[dict]) -> list[dict]:
        cleaned = []
        for req in requirements:
            req_type = req.get("type")
            field_value = req.get("field_value") or req.get("value") or ""
            if req_type not in {"must", "bonus"}:
                continue
            if not str(field_value).strip():
                continue
            cleaned.append(req)
        return cleaned
