"""Local browser interface. Run: python app.py. No cloud services are used."""

from __future__ import annotations

import argparse
import base64
import binascii
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit
import webbrowser

from PIL import Image

from steganography import MAX_FILE_BYTES, SteganographyError, decode, encode, inspect_image

ROOT = Path(__file__).resolve().parent
MAX_REQUEST = 17 * 1024 * 1024
ASSETS = {"/": ("web/index.html", "text/html; charset=utf-8"),
          "/style.css": ("web/style.css", "text/css; charset=utf-8"),
          "/app.js": ("web/app.js", "text/javascript; charset=utf-8")}


def make_demo() -> bytes:
    """A reproducible colour study that students can replace with their own PNG."""
    width, height = 720, 480
    raw = bytearray()
    for y in range(height):
        for x in range(width):
            # Smooth RGB gradients with a subtle checker texture for a test cover.
            texture = 6 if ((x // 48) + (y // 48)) % 2 else 0
            raw.extend((min(255, 24 + x * 126 // width + texture),
                        min(255, 52 + y * 136 // height + texture),
                        min(255, 110 + (width - x) * 104 // width)))
    image = Image.frombytes("RGB", (width, height), bytes(raw))
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def process_action(action: str, body: dict) -> dict:
    if not isinstance(body, dict) or not isinstance(body.get("image"), str):
        raise SteganographyError("Select a PNG image first.")
    if len(body["image"]) > ((MAX_FILE_BYTES + 2) // 3) * 4:
        raise SteganographyError("Choose a PNG no larger than 12 MiB.")
    try:
        data = base64.b64decode(body["image"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise SteganographyError("The image upload is invalid. Please select it again.") from exc
    if action == "inspect":
        return inspect_image(data)
    if action == "hide":
        result = encode(data, body.get("message"))
        return {"image": base64.b64encode(result.png).decode("ascii"), "metrics": result.metrics}
    if action == "extract":
        return decode(data)
    raise SteganographyError("Unknown action.")


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def log_message(self, *_args):
        # Avoid logging message text, file names or image contents.
        pass

    def _send(self, status: int, data: bytes, mime: str):
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data: blob:; "
                         "style-src 'self'; script-src 'self'; connect-src 'self'; "
                         "object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, status: int, value: dict):
        self._send(status, json.dumps(value, ensure_ascii=True).encode(), "application/json")

    def _reject(self, status: int, message: str):
        # Drain a bounded request before closing so the error response is not
        # replaced by a TCP reset when the browser is still sending its body.
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if 0 < size <= MAX_REQUEST:
                self.connection.settimeout(3)
                self.rfile.read(size)
        except (ValueError, OSError):
            pass
        self._json(status, {"error": message})

    def _local_request(self) -> bool:
        port = self.server.server_address[1]
        allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        origin = self.headers.get("Origin")
        return (self.headers.get("Host") in allowed_hosts
                and self.headers.get("Sec-Fetch-Site") != "cross-site"
                and (origin is None or origin in {f"http://{h}" for h in allowed_hosts}))

    def do_GET(self):
        if not self._local_request():
            self._json(403, {"error": "Open this app through its local address."})
            return
        route = urlsplit(self.path).path
        if route == "/api/demo":
            self._send(200, make_demo(), "image/png")
        elif route in ASSETS:
            filename, mime = ASSETS[route]
            self._send(200, (ROOT / filename).read_bytes(), mime)
        elif route == "/favicon.ico":
            self._send(204, b"", "image/x-icon")
        else:
            self._json(404, {"error": "Page not found."})

    def do_POST(self):
        if not self._local_request():
            self._reject(403, "Requests must come from this local app.")
            return
        route = urlsplit(self.path).path
        if route not in {"/api/inspect", "/api/hide", "/api/extract"}:
            self._reject(404, "Action not found.")
            return
        if self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
            self._reject(415, "Expected an image upload from the app.")
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > MAX_REQUEST:
                self._json(413, {"error": "The upload is too large or empty. Maximum PNG size is 12 MiB."})
                return
            self.connection.settimeout(30)
            body = json.loads(self.rfile.read(size))
            result = process_action(route.rsplit("/", 1)[1], body)
            self._json(200, result)
        except (SteganographyError, ValueError, UnicodeError) as exc:
            message = str(exc) if isinstance(exc, SteganographyError) else "The request is invalid. Please try again."
            self._json(400, {"error": message})
        except TimeoutError:
            self._json(408, {"error": "The upload timed out. Please try again."})
        except Exception:
            self._json(500, {"error": "The image could not be processed. Try a smaller PNG."})


def main():
    parser = argparse.ArgumentParser(description="CNS image steganography mini project")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Choose a port between 1 and 65535.")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    except OSError:
        parser.exit(1, "The local port is unavailable. Try: python app.py --port 8766\n")
    url = f"http://127.0.0.1:{args.port}"
    print(f"\nImage Steganography is running at {url}\nKeep this window open. Press Ctrl+C to stop.\n")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
