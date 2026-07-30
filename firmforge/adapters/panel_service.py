"""Serial Panel HTTP Service.

Independent HTTP server serving the serial live panel (panel.html)
and all related endpoints: Serial tab + MODBUS tab.

Exposed functions:
  - start_panel_httpd(root) -> int  (starts HTTP server, returns port)
  - get_stream_queue() -> Queue
  - clear_stream_queue()
"""

import logging
import os
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

logger = logging.getLogger("firmforge.panel")

_panel_httpd = None
_stream_queue = None


def get_stream_queue():
    """Return the shared SSE queue, creating it if needed."""
    global _stream_queue
    if _stream_queue is None:
        import queue as _q
        _stream_queue = _q.Queue()
    return _stream_queue


def clear_stream_queue():
    """Reset the stream queue (call after collector exits)."""
    global _stream_queue
    _stream_queue = None


def start_panel_httpd(root: str) -> int:
    """Start HTTP server serving .firmforge/ on port 9878. Returns port.
    Singleton: each call shuts down the old server and creates a fresh one.
    """
    global _panel_httpd
    try:
        if _panel_httpd is not None:
            _panel_httpd.shutdown()
    except Exception:
        pass
    _panel_httpd = None

    class _ThreadedPanelServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    data_dir = os.path.join(root, ".firmforge")
    stop_file = os.path.join(data_dir, "serial_live.html.stop")
    pause_file = os.path.join(data_dir, "serial_live.html.pause")
    serial_write_file = os.path.join(data_dir, "serial_write.json")
    modbus_request_file = os.path.join(data_dir, "modbus_request.json")
    modbus_response_file = os.path.join(data_dir, "modbus_response.json")

    class _PanelHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=data_dir, **kw)

        def do_GET(self):
            if self.path == "/stream":
                self._handle_sse()
                return
            super().do_GET()

        def _handle_sse(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            q = get_stream_queue()
            try:
                while True:
                    try:
                        item = q.get(timeout=3)
                        import json as _j
                        data = _j.dumps(item, ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode())
                        self.wfile.flush()
                    except Exception:
                        self.wfile.write(b": hb\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                # Client disconnected (panel closed) — signal collector to stop
                try:
                    with open(stop_file, "w") as f: f.write("x")
                except Exception:
                    pass

        def do_POST(self):
            if self.path == "/serial-stop":
                # Full exit: write .stop
                try:
                    with open(pause_file, "w") as f: f.write("x")
                    with open(stop_file, "w") as f: f.write("x")
                except Exception:
                    pass
                self._json({"ok": True})

            elif self.path == "/serial-close":
                # Pause COM4 only, keep process alive
                try:
                    with open(pause_file, "w") as f: f.write("x")
                except Exception:
                    pass
                self._json({"ok": True, "paused": True})

            elif self.path == "/serial-open":
                # Resume COM4
                try:
                    os.remove(pause_file)
                except OSError:
                    pass
                try:
                    os.remove(stop_file)
                except OSError:
                    pass
                self._json({"ok": True, "resumed": True})

            elif self.path == "/serial-send":
                self._save_body(serial_write_file)
                self._json({"ok": True})

            elif self.path == "/modbus":
                length = int(self.headers.get("Content-Length", "0"))
                body_bytes = self.rfile.read(length)
                try:
                    with open(modbus_request_file, "wb") as f:
                        f.write(body_bytes)
                except Exception:
                    pass
                # Poll for response (collector thread processes the command)
                raw_hex = ""
                error = ""
                for _ in range(50):  # up to 5s
                    time.sleep(0.1)
                    if os.path.exists(modbus_response_file):
                        try:
                            import json as _j
                            with open(modbus_response_file) as f:
                                md = _j.load(f)
                            raw_hex = md.get("raw", "")
                            error = md.get("error", "")
                            os.remove(modbus_response_file)
                        except Exception as e:
                            error = str(e)
                        break
                self._json({"ok": True, "raw": raw_hex, "error": error})

            elif self.path == "/quit":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"BYE")
                os._exit(0)

        def _json(self, data):
            import json as _j
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(_j.dumps(data).encode())

        def _save_body(self, path):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                with open(path, "wb") as f:
                    f.write(self.rfile.read(length))
            except Exception:
                pass

        def end_headers(self):
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            super().end_headers()

        def log_message(self, *a):
            pass

        def log_error(self, *a):
            pass

    for p in range(9878, 9888):
        try:
            _panel_httpd = _ThreadedPanelServer(("127.0.0.1", p), _PanelHandler)
            threading.Thread(target=_panel_httpd.serve_forever, daemon=True).start()
            logger.info("Panel HTTP server started on port %d", p)
            return p
        except Exception as e:
            logger.warning("Panel HTTP port %d failed: %s", p, e)
    return 0
