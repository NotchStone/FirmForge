"""Integration tests for panel_service HTTP routes."""

import http.client
import json

import pytest

from firmforge.adapters import panel_service as ps


@pytest.fixture
def server(temp_dir):
    """Start the panel HTTP server against a temp dir; yield (port, dir)."""
    import time
    (temp_dir / ".firmforge").mkdir(exist_ok=True)
    (temp_dir / ".firmforge" / "serial_live.html").write_text(
        "<html><body>FirmForge test panel</body></html>", encoding="utf-8")
    port = ps.start_panel_httpd(str(temp_dir))
    assert port, "panel server failed to bind"
    time.sleep(0.3)  # let serve_forever thread accept connections
    yield port, temp_dir
    try:
        ps._panel_httpd.shutdown()
    except Exception:
        pass
    time.sleep(0.1)


def _post(port, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    conn.request("POST", path, body=data, headers=headers)
    resp = conn.getresponse()
    out = json.loads(resp.read().decode() or "{}")
    conn.close()
    return out


def _get(port, path):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    return resp.status, data


class TestPanelRoutes:
    def test_serial_live_served(self, server):
        port, _ = server
        status, data = _get(port, "/serial_live.html")
        assert status == 200
        assert b"FirmForge" in data

    def test_serial_send_writes_file(self, server):
        port, tmp = server
        out = _post(port, "/serial-send", {"text": "hello", "hex": False, "crlf": True})
        assert out["ok"] is True
        f = tmp / ".firmforge" / "serial_write.json"
        assert f.exists()
        data = json.loads(f.read_text())
        assert data["text"] == "hello"

    def test_serial_config_writes_config(self, server):
        port, tmp = server
        out = _post(port, "/serial-config", {"baud": 57600, "parity": "Even"})
        assert out["ok"] is True
        f = tmp / ".firmforge" / "serial_config.json"
        assert f.exists()
        cfg = json.loads(f.read_text())
        assert cfg == {"baud": 57600, "parity": "Even"}

    def test_serial_config_invalid_body(self, server):
        port, _ = server
        out = _post(port, "/serial-config", {"baud": "abc"})
        assert out["ok"] is False

    def test_serial_close_creates_pause(self, server):
        port, tmp = server
        _post(port, "/serial-close")
        assert (tmp / ".firmforge" / "serial_live.html.pause").exists()

    def test_serial_open_removes_pause(self, server):
        port, tmp = server
        pause = tmp / ".firmforge" / "serial_live.html.pause"
        pause.write_text("x")
        _post(port, "/serial-open")
        assert not pause.exists()

    def test_modbus_roundtrip_via_queue(self, server):
        port, _ = server
        # Simulate collector: pre-place a response, then send a request
        def _fake_collector():
            req = ps.get_modbus_request_queue().get(timeout=3)
            ps.get_modbus_response_queue().put(
                {"raw": "01 03 02 12 34 B5 33", "crc_ok": True,
                 "regs": [0x1234], "rx_bytes": 7, "tx_bytes": 8})
        import threading
        t = threading.Thread(target=_fake_collector, daemon=True)
        t.start()
        out = _post(port, "/modbus", {"mb": {"slave": 1, "fc": 3, "addr": 0, "count": 1}})
        assert out["ok"] is True
        assert out["raw"] == "01 03 02 12 34 B5 33"
        assert out["rx"] == 7 and out["tx"] == 8

    def test_modbus_timeout_returns_ok_false(self, server):
        port, _ = server
        out = _post(port, "/modbus", {"mb": {"slave": 1, "fc": 3, "addr": 0, "count": 1}})
        assert out["ok"] is False
        assert "timeout" in out["error"]
