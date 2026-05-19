from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ._utils import json_response, supabase_request


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        json_response(self, {"ok": True})

    def do_GET(self) -> None:
        try:
            params = parse_qs(urlparse(self.path).query)
            organization_id = (params.get("organization_id") or [""])[0]
            if not organization_id:
                raise ValueError("organization_id 不能为空")
            query = {
                "organization_id": f"eq.{organization_id}",
                "select": "*,jobs(title),resumes(candidate_name,file_name)",
                "order": "created_at.desc",
            }
            if params.get("job_id"):
                query["job_id"] = f"eq.{params['job_id'][0]}"
            if params.get("conclusion"):
                query["conclusion"] = f"eq.{params['conclusion'][0]}"
            results = supabase_request("GET", "screening_results", query=query)
            json_response(self, {"items": results or []})
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=400)

    def do_DELETE(self) -> None:
        try:
            params = parse_qs(urlparse(self.path).query)
            organization_id = (params.get("organization_id") or [""])[0]
            result_id = (params.get("id") or [""])[0]
            if not organization_id:
                raise ValueError("organization_id 不能为空")
            if not result_id:
                raise ValueError("id 不能为空")
            supabase_request(
                "DELETE",
                "screening_results",
                query={"id": f"eq.{result_id}", "organization_id": f"eq.{organization_id}"},
            )
            json_response(self, {"ok": True})
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=400)
