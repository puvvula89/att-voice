"""Static file server for the demo frontend.

Plain `python -m http.server` sends no Cache-Control and answers conditional
requests with 304, so a browser caches the UNVERSIONED entry points (index.html,
chat.html, config.js) and keeps serving an old index.html that still references
the previous ?v= module URLs — i.e. a redeploy doesn't take effect until a hard
refresh. This server sends `Cache-Control: no-store` on every response and strips
the conditional/validator headers so the browser always re-fetches fresh. The
versioned modules (client.js?v=N) would be safe to cache, but no-store everywhere
is the simplest guarantee for a demo and the payload is tiny.
"""
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class NoCacheHandler(SimpleHTTPRequestHandler):
    def _strip_conditionals(self):
        # Drop client validators so SimpleHTTPRequestHandler.send_head() never
        # short-circuits to a 304 — always serve the full, current file.
        for h in ("If-Modified-Since", "If-None-Match"):
            try:
                del self.headers[h]
            except KeyError:
                pass

    def do_GET(self):
        self._strip_conditionals()
        super().do_GET()

    def do_HEAD(self):
        self._strip_conditionals()
        super().do_HEAD()

    def send_header(self, keyword, value):
        # Suppress validators so the browser can't cache/revalidate stale assets.
        if keyword.lower() in ("last-modified", "etag"):
            return
        super().send_header(keyword, value)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    ThreadingHTTPServer(("", port), NoCacheHandler).serve_forever()
