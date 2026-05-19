from __future__ import annotations

from http.server import BaseHTTPRequestHandler
import os

from ._utils import json_response


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        json_response(self, {"ok": True})

    def do_GET(self) -> None:
        json_response(
            self,
            {
                "ok": True,
                "runtime": "vercel-python",
                "supabase_configured": bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY")),
                "llm_configured": bool(os.environ.get("RESUME_SCREENER_LLM_API_KEY")),
            },
        )
