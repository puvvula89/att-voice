import http.server
import socketserver

PORT = 8000


class NoCache(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_header(self, key, value):
        if key.lower() in ("last-modified", "etag"):
            return
        super().send_header(key, value)


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), NoCache) as httpd:
        print(f"harness at http://localhost:{PORT}/client.html")
        httpd.serve_forever()
