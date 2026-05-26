# ground_server.py — AI Monitor Ground HTTP Server
# ──────────────────────────────────────────────────────────────────────────────
# Lightweight local-only HTTP server. Lets any tool — MCP, scripts, editors,
# future agents — read from and write to the shared ground without importing
# Python modules directly.
#
# Runs on localhost:7734 by default (change PORT below if needed).
# Start it once; leave it running in the background.
#
# Endpoints:
#   GET  /health                → {"status": "ok", "sources": {...}}
#   GET  /context               → plain text compressed ground context
#   GET  /ground                → full ground state JSON
#   GET  /search?q=QUERY        → semantic + FTS5 search results JSON
#   POST /contribute            → add knowledge to the ground
#     body: {"content": "...", "source": "claude|gemini_cli|...", "mode": "exchange"}
#   GET  /stats                 → memory statistics JSON
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import os
import sys
import json
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("GROUND_PORT", 7734))

# ── Path bootstrap ─────────────────────────────────────────────────────────────
_HERE     = Path(__file__).resolve().parent
_WON_ROOT = Path(os.environ.get("WON_PATH", str(_HERE)))
for p in [str(_HERE), str(_WON_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)

try:
    import perception as _perception
    PERCEPTION_OK = True
except Exception as exc:
    PERCEPTION_OK = False
    print(f"[GroundServer] Perception unavailable — {exc}", file=sys.stderr)

try:
    import pipeline as _pipeline
    PIPELINE_OK = True
except Exception:
    PIPELINE_OK = False


# ── Request handler ────────────────────────────────────────────────────────────

class GroundHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Suppress default access log — use our own
        ts = datetime.now().strftime("%H:%M:%S")
        print(f"  [{ts}] {self.command} {self.path}", flush=True)

    def _send(self, code: int, body: str | dict, content_type: str = "application/json"):
        if isinstance(body, dict):
            body = json.dumps(body, indent=2, ensure_ascii=False)
        enc = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(enc)))
        self.send_header("Access-Control-Allow-Origin", "*")  # local tools only
        self.end_headers()
        self.wfile.write(enc)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        if path == "/health":
            state   = _perception._load_ground() if PERCEPTION_OK else {}
            sources = state.get("sources", {})
            self._send(200, {
                "status":     "ok",
                "perception": PERCEPTION_OK,
                "pipeline":   PIPELINE_OK,
                "sources":    sources,
                "ts":         datetime.utcnow().isoformat(),
            })

        elif path == "/context":
            ctx = _perception.get_compressed_context() if PERCEPTION_OK else ""
            self._send(200, ctx, content_type="text/plain; charset=utf-8")

        elif path == "/ground":
            if PERCEPTION_OK:
                state = _perception._load_ground()
                self._send(200, state)
            else:
                self._send(503, {"error": "perception offline"})

        elif path == "/search":
            q = params.get("q", [""])[0].strip()
            if not q:
                self._send(400, {"error": "missing q parameter"})
                return
            limit   = int(params.get("limit", ["8"])[0])
            results = _perception.search(q, limit=limit) if PERCEPTION_OK else []
            self._send(200, {"query": q, "count": len(results), "results": results})

        elif path == "/stats":
            stats = _pipeline.stats() if PIPELINE_OK else {}
            self._send(200, stats)

        elif path == "/inject":
            # Returns a formatted injection block for pasting into a new chat
            block = _perception.format_for_injection() if PERCEPTION_OK else ""
            self._send(200, block, content_type="text/plain; charset=utf-8")

        else:
            self._send(404, {"error": f"unknown endpoint: {path}"})

    def do_POST(self):
        parsed = urlparse(self.path)
        path   = parsed.path.rstrip("/")

        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length).decode("utf-8") if length else "{}"
        try:
            data = json.loads(body)
        except Exception:
            self._send(400, {"error": "invalid JSON"})
            return

        if path == "/contribute":
            content = (data.get("content") or "").strip()
            source  = data.get("source", "pipeline")
            mode    = data.get("mode", "exchange")
            tags    = data.get("tags", [])

            if not content:
                self._send(400, {"error": "content required"})
                return

            ok = _perception.contribute(content, source=source, mode=mode, tags=tags) \
                 if PERCEPTION_OK else False

            self._send(200, {"ok": ok, "source": source, "mode": mode})

        elif path == "/process":
            # Full pipeline process (same as browser extension capture)
            data.get("platform", "unknown")
            summary   = (data.get("summary") or "").strip()
            int(data.get("messageCount") or 0)
            if not summary:
                self._send(400, {"error": "summary required"})
                return
            result = _pipeline.process(data) if PIPELINE_OK else {}
            self._send(200, result)

        else:
            self._send(404, {"error": f"unknown endpoint: {path}"})


# ── Server startup ─────────────────────────────────────────────────────────────

def main():
    server = HTTPServer(("127.0.0.1", PORT), GroundHandler)
    print(f"""
╔══════════════════════════════════════════════╗
║   AI Monitor — Ground Server                ║
║   http://127.0.0.1:{PORT}                     ║
╚══════════════════════════════════════════════╝

  GET  /context        → compressed context (paste into any chat)
  GET  /ground         → full ground state JSON
  GET  /search?q=...   → semantic + FTS5 search
  POST /contribute     → add knowledge from any source
  POST /process        → full pipeline (capture + brief + Obsidian)
  GET  /inject         → formatted injection block
  GET  /health         → status + source activity
  GET  /stats          → memory statistics

  Perception: {'✓ ONLINE' if PERCEPTION_OK else '✗ OFFLINE'}
  Pipeline:   {'✓ ONLINE' if PIPELINE_OK   else '✗ OFFLINE'}

  Ctrl+C to stop.
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[GroundServer] Stopped.")


if __name__ == "__main__":
    main()
