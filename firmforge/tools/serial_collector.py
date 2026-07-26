"""Serial collector — writes live HTML with JS polling.

Usage: python serial_collector.py <html_path> <port> <baud>
Stop: create <html_path>.stop file, collector exits within 1s
"""

import sys
import time
import os
import signal
import atexit

html_path = sys.argv[1]
port_name = sys.argv[2]
baud = int(sys.argv[3])
timeout_s = int(sys.argv[4]) if len(sys.argv) > 4 else 0
stop_file = html_path + ".stop"
_start_time = time.time()

lines = []
ser = None


def cleanup():
    try:
        os.unlink(stop_file)
    except Exception:
        pass


signal.signal(signal.SIGINT, lambda *_: (cleanup(), os._exit(0)))
signal.signal(signal.SIGTERM, lambda *_: (cleanup(), os._exit(0)))
atexit.register(cleanup)


def write_html():
    rows = "".join(
        f'<div class="line">{ln}</div>\n'
        for ln in lines[-100:]
    )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8">
<title>FirmForge Serial Live</title>
<style>
:root{{--bg:#1a1a2e;--panel:#16213e;--text:#e0e0e0;--accent:#00d4aa;--warn:#ff6b6b;--dim:#666;--border:#2a2a4a}}
*{{margin:0;padding:0;box-sizing:border-box}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:8px;background:var(--accent);transition:background 0.5s}}
body{{background:var(--bg);color:var(--text);font-family:'Cascadia Code','Fira Code',Consolas,monospace;font-size:13px;height:100vh;display:flex;flex-direction:column}}
.header{{background:var(--panel);padding:8px 16px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;font-size:12px;flex-shrink:0}}
.port{{color:var(--accent)}}
.output{{flex:1;overflow-y:auto;padding:10px 16px;line-height:1.6}}
.output .line{{padding:2px 0;border-bottom:1px solid rgba(255,255,255,0.03);white-space:pre-wrap;word-break:break-all}}
.footer{{background:var(--panel);padding:5px 16px;border-top:1px solid var(--border);font-size:11px;color:var(--dim);text-align:center;flex-shrink:0}}
@media(prefers-color-scheme:light){{:root{{--bg:#f5f5f5;--panel:#e8e8e8;--text:#333;--dim:#888;--border:#ddd;--accent:#007bff;--warn:#d32f2f}}}}
</style>
</head>
<body>
<div class="header">
  <span><span class="dot" id="dot"></span><span class="port">{port_name} @ {baud} baud</span></span>
  <span id="info">{len(lines)} lines | {time.strftime('%H:%M:%S')}</span>
</div>
<div class="output" id="output">
{rows}
</div>
<div class="footer">FirmForge Serial Monitor</div>
<script>
let cur = 0, out = document.getElementById('output'), dot = document.getElementById('dot');
setInterval(async () => {{
  try {{
    let r = await fetch(location.pathname.split('?')[0] + '?t=' + Date.now(), {{cache:'no-store'}});
    let t = await r.text();
    let m = t.match(/<div class="output" id="output">([\\s\\S]*?)<\\/div>/);
    if (!m) return;
    let n = (m[1].match(/<div class="line">/g) || []).length;
    if (n !== cur) {{
      cur = n; out.innerHTML = m[1]; out.scrollTop = out.scrollHeight;
    }}
    let info = t.match(/<span id="info">([^<]*)<\\/span>/);
    if (info) document.getElementById('info').innerHTML = info[1];
    // Status dot: green if updated within 3s, red otherwise
    let time = t.match(/\| (\d{{2}}:\d{{2}}:\d{{2}})<\\/span>/);
    if (time) {{
      let fileHms = time[1].split(':').map(Number);
      let now = new Date();
      let fileSec = fileHms[0]*3600 + fileHms[1]*60 + fileHms[2];
      let nowSec = now.getHours()*3600 + now.getMinutes()*60 + now.getSeconds();
      let diff = Math.abs(nowSec - fileSec);
      diff = Math.min(diff, 86400 - diff);
      dot.style.background = diff < 3 ? 'var(--accent)' : 'var(--warn,#ff6b6b)';
    }}
  }} catch(e) {{}}
}}, 500);
window.onload = () => out.scrollTop = out.scrollHeight;
</script>
</body></html>"""
    try:
        os.makedirs(os.path.dirname(html_path), exist_ok=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass


# Initial write
write_html()

# Main loop — uses ComPort (pySerial → Win32Serial fallback, same pattern as S5)
try:
    sys.path.insert(0, os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))))
    from firmforge.providers.com_port import ComPort

    with ComPort(port_name, baud, timeout=0.3) as ser:
        time.sleep(0.5)
        try:
            ser.reset_input_buffer()
        except Exception:
            pass
        buf = ""
        last_write = time.time()

        write_html()

        while True:
            if os.path.exists(stop_file):
                break
            if timeout_s > 0 and time.time() - _start_time > timeout_s:
                break

            try:
                chunk = ser.read(64)
            except Exception:
                time.sleep(0.5)
                continue

            if chunk:
            if chunk:
                if isinstance(chunk, bytes):
                    chunk = chunk.decode("ascii", errors="replace")
                buf += chunk
                while chr(10) in buf:
                    line, buf = buf.split(chr(10), 1)
                    line = line.rstrip(chr(13))
                    if line:
                        lines.append(line)
                        if len(lines) > 500:
                            lines = lines[-500:]

            now = time.time()
            if now - last_write >= 0.3:
                write_html()
                last_write = now

            time.sleep(0.05)

except Exception:
    pass
