"""Serial collector — writes live HTML with iframe-based silent refresh.

Usage: python serial_collector.py <html_path> <port> <baud>
"""

import sys
import time
import os
import signal
import atexit

html_path = sys.argv[1]
port_name = sys.argv[2]
baud = int(sys.argv[3])
stop_file = html_path + ".stop"

lines = []
ser = None


def cleanup():
    global ser
    if ser is not None:
        try:
            ser.close()
        except Exception:
            pass
        ser = None
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

# Main loop
try:
    import serial
    ser = serial.Serial(port_name, baud, timeout=0.5)
    ser.reset_input_buffer()
    buf = ""
    last_write = time.time()

    while True:
        if os.path.exists(stop_file):
            break

        data = ser.read(ser.in_waiting or 1)
        changed = False
        if data:
            text = data.decode("ascii", errors="replace")
            buf += text
            while chr(10) in buf:
                line, buf = buf.split(chr(10), 1)
                line = line.rstrip(chr(13))
                if line:
                    lines.append(line)
                    if len(lines) > 500:
                        lines = lines[-500:]
                    changed = True

        now = time.time()
        if changed or (now - last_write >= 3):
            write_html()
            last_write = now

        time.sleep(0.1)

except Exception:
    pass
finally:
    cleanup()
