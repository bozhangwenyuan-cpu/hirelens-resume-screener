from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import os

from ._utils import json_response


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        json_response(self, {"ok": True})

    def do_GET(self) -> None:
        required = [
            "SUPABASE_URL",
            "SUPABASE_SERVICE_ROLE_KEY",
            "RESUME_SCREENER_LLM_API_KEY",
        ]
        missing = [name for name in required if not os.environ.get(name)]
        json_response(
            self,
            {
                "ok": not missing,
                "runtime": "vercel-python",
                "missing_env": missing,
                "supabase_url_configured": bool(os.environ.get("SUPABASE_URL")),
                "supabase_service_role_configured": bool(os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
                "supabase_configured": bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
                "llm_configured": bool(os.environ.get("RESUME_SCREENER_LLM_API_KEY")),
                "vision_model_configured": bool(os.environ.get("RESUME_SCREENER_VISION_MODEL")),
                "vision_api_configured": bool(os.environ.get("RESUME_SCREENER_VISION_API_KEY") or os.environ.get("OPENAI_API_KEY")),
            },
        )
