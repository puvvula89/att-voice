"""Demo web page with the chat widget. The widget talks to the agent platform directly; this server
only serves the page, filling in the widget deployment it should use from CHAT_DEPLOYMENT."""
import html
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
ASSETS = {p.name: p for p in (HERE / "assets").glob("*") if p.suffix in (".png", ".jpg", ".svg")}
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".svg": "image/svg+xml"}


def page() -> bytes:
    text = (HERE / "index.html").read_text()
    return (text.replace("CHAT_DEPLOYMENT", html.escape(os.environ.get("CHAT_DEPLOYMENT", ""), quote=True))
                .replace("CHAT_TITLE", html.escape(os.environ.get("CHAT_TITLE", "Cricket Support"), quote=True))
                .replace("CHAT_USER", html.escape(os.environ.get("CHAT_USER", "Jordan"), quote=True))).encode()


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        asset = ASSETS.get(path[len("/assets/"):]) if path.startswith("/assets/") else None
        if asset:
            body, kind, cache = asset.read_bytes(), TYPES[asset.suffix], "public, max-age=3600"
        elif path in ("/", "/index.html"):
            body, kind, cache = page(), "text/html; charset=utf-8", "no-store"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8080"))), Handler).serve_forever()
