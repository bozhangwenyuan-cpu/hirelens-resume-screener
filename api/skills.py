from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from ._utils import json_response, read_json, supabase_request


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        json_response(self, {"ok": True})

    def do_GET(self) -> None:
        try:
            params = parse_qs(urlparse(self.path).query)
            organization_id = (params.get("organization_id") or [""])[0]
            if not organization_id:
                raise ValueError("organization_id 不能为空")
            skills = supabase_request(
                "GET",
                "screening_skills",
                query={
                    "organization_id": f"eq.{organization_id}",
                    "select": "*",
                    "order": "updated_at.desc",
                },
            )
            json_response(self, {"items": skills or []})
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=400)

    def do_POST(self) -> None:
        try:
            payload = read_json(self)
            organization_id = payload.get("organization_id")
            if not organization_id:
                raise ValueError("organization_id 不能为空")
            rows = supabase_request(
                "POST",
                "screening_skills",
                {
                    "organization_id": organization_id,
                    "name": payload.get("name") or "未命名 Skill",
                    "category": payload.get("category") or "通用",
                    "description": payload.get("description") or "",
                    "instruction": payload.get("instruction") or "",
                    "strictness": payload.get("strictness") or "balanced",
                    "status": payload.get("status") or "active",
                    "is_system": bool(payload.get("is_system") or False),
                },
                prefer="return=representation",
            )
            json_response(self, rows[0], status=201)
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=400)

    def do_PATCH(self) -> None:
        try:
            payload = read_json(self)
            organization_id = payload.get("organization_id")
            skill_id = payload.get("id")
            if not organization_id:
                raise ValueError("organization_id 不能为空")
            if not skill_id:
                raise ValueError("id 不能为空")
            rows = supabase_request(
                "PATCH",
                "screening_skills",
                {
                    "name": payload.get("name") or "未命名 Skill",
                    "category": payload.get("category") or "通用",
                    "description": payload.get("description") or "",
                    "instruction": payload.get("instruction") or "",
                    "strictness": payload.get("strictness") or "balanced",
                    "status": payload.get("status") or "active",
                },
                query={"id": f"eq.{skill_id}", "organization_id": f"eq.{organization_id}"},
                prefer="return=representation",
            )
            if not rows:
                raise ValueError("Skill 不存在")
            json_response(self, rows[0])
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=400)

    def do_DELETE(self) -> None:
        try:
            params = parse_qs(urlparse(self.path).query)
            organization_id = (params.get("organization_id") or [""])[0]
            skill_id = (params.get("id") or [""])[0]
            if not organization_id:
                raise ValueError("organization_id 不能为空")
            if not skill_id:
                raise ValueError("id 不能为空")
            supabase_request(
                "DELETE",
                "screening_skills",
                query={"id": f"eq.{skill_id}", "organization_id": f"eq.{organization_id}", "is_system": "eq.false"},
            )
            json_response(self, {"ok": True})
        except Exception as exc:
            json_response(self, {"error": str(exc)}, status=400)
