
"""Still Here - lightweight operator API."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json

HOST = "127.0.0.1"
PORT = 8000

# Temporary demo state; later connect this to run.py and report.py.
STATE = {
    "plan": None,
    "approved": False,
    "report": None,
}


class OperatorHandler(BaseHTTPRequestHandler):
    def send_json(self, status_code, data):
        body = json.dumps(data, indent=2).encode("utf-8")

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self.send_json(200, {
                "service": "Still Here Operator API",
                "endpoints": [
                    "GET /plan",
                    "GET /report",
                    "GET /video",
                    "POST /approve",
                ],
            })

        elif self.path == "/plan":
            self.send_json(200, {"plan": STATE["plan"]})

        elif self.path == "/report":
            self.send_json(200, {"report": STATE["report"]})

        elif self.path == "/video":
            self.send_json(200, {
                "video_url": None,
                "message": "Demo video endpoint; connect the video source later.",
            })

        else:
            self.send_json(404, {"error": "Endpoint not found"})

    def do_POST(self):
        if self.path != "/approve":
            self.send_json(404, {"error": "Endpoint not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))

        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self.send_json(400, {"error": "Invalid JSON"})
            return

        if payload.get("approved") is not True:
            STATE["approved"] = False
            self.send_json(200, {
                "approved": False,
                "message": "Plan was not approved.",
            })
            return

        if STATE["plan"] is None:
            self.send_json(409, {
                "error": "There is no plan to approve yet."
            })
            return

        STATE["approved"] = True
        self.send_json(200, {
            "approved": True,
            "message": "Plan approval recorded.",
        })

    def log_message(self, format_string, *args):
        # Keep the terminal output simple during the demo.
        print("%s - %s" % (self.address_string(), format_string % args))


def start_server():
    server = HTTPServer((HOST, PORT), OperatorHandler)
    print(f"Still Here API running at http://{HOST}:{PORT}")
    print("Press Ctrl+C to stop the server.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        server.server_close()


if __name__ == "__main__":
    start_server()
