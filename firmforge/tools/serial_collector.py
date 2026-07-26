"""Serial collector — writes live HTML with XHR polling + optional sample JSON.

Usage: python serial_collector.py <html_path> <port> <baud> [timeout] [--sample <json>]
  --sample <path> : write 3 sample lines to JSON path, then continue HTML output
                    (used by ff_run S5 Verify to feed Agent)

Stop: create <html_path>.stop file

Uses ComPort (Win32Serial → pySerial fallback) to avoid CH340 deadlock.
Same proven pattern as pipeline S5 test stage.
"""

import sys
import time
import os
import atexit

html_path = sys.argv[1]
port_name = sys.argv[2]
baud = int(sys.argv[3])
timeout_s = int(sys.argv[4]) if len(sys.argv) > 4 else 0
sample_path = ""
_sample_timeout = 8.0  # seconds to wait for sample lines

idx = 5
while idx < len(sys.argv):
    if sys.argv[idx] == "--sample" and idx + 1 < len(sys.argv):
        sample_path = sys.argv[idx + 1]
        idx += 2
    elif sys.argv[idx] == "--sample-timeout" and idx + 1 < len(sys.argv):
        _sample_timeout = float(sys.argv[idx + 1])
        idx += 2
    else:
        idx += 1

stop_file = html_path + ".stop"
_start_time = time.time()
data_dir = os.path.dirname(os.path.abspath(html_path))
pid_file = os.path.join(data_dir, "collector.pid")

# Write PID for process management
try:
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))
except Exception:
    pass

lines = []


def cleanup():
    try:
        os.unlink(stop_file)
    except Exception:
        pass
    try:
        os.unlink(pid_file)
    except Exception:
        pass


atexit.register(cleanup)


# ---------- HTML template ----------
def write_html():
    ts = time.strftime('%H:%M:%S')
    rows = "".join(f'<div class="line">{ln}</div>\n' for ln in lines)
    cnt = len(lines)

    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="UTF-8"><title>FirmForge Serial</title>
<style>
:root{{--bg:#0f172a;--hdr:#1e293b;--txt:#e2e8f0;--dim:#64748b;--acc:#22d3ee;--warn:#ef4444;--btn-bg:#334155;--btn-hover:#475569;--sep:#2d3748}}
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:var(--bg);color:var(--txt);font-family:'Segoe UI',system-ui,sans-serif;font-size:13px;height:100vh;display:flex;flex-direction:column;-webkit-font-smoothing:antialiased}}
.tbar{{display:flex;align-items:center;gap:12px;padding:6px 14px;background:var(--hdr);border-bottom:1px solid var(--sep);flex-shrink:0;min-height:36px}}
.tbar .l{{display:flex;align-items:center;gap:8px;flex:1;min-width:0}}
.tbar .r{{display:flex;align-items:center;gap:6px}}
.dot{{width:8px;height:8px;border-radius:50%;background:var(--acc);flex-shrink:0}}
.port{{color:var(--acc);font-weight:600;font-size:13px}}
.baud{{color:var(--dim);font-size:11px}}
.count{{color:var(--dim);font-size:11px;white-space:nowrap}}
.sep{{width:1px;height:16px;background:var(--sep);margin:0 4px}}
.btn{{border:1px solid var(--sep);background:var(--btn-bg);color:var(--txt);padding:3px 10px;border-radius:4px;cursor:pointer;font-size:11px;transition:background .15s}}
.btn:hover{{background:var(--btn-hover)}}
.btn.danger{{background:var(--warn);border-color:var(--warn);color:#fff}}
.btn.danger:hover{{opacity:.85}}
.out{{flex:1;overflow-y:auto;padding:8px 14px;font-family:'Cascadia Code',Consolas,monospace;font-size:12.5px;line-height:1.55}}
.line{{padding:1px 0;border-bottom:1px solid rgba(255,255,255,.02);white-space:pre-wrap;word-break:break-all}}
.ftr{{padding:4px 14px;text-align:center;font-size:10px;color:var(--dim);border-top:1px solid var(--sep);background:var(--hdr);flex-shrink:0}}
@media(prefers-color-scheme:light){{:root{{--bg:#f1f5f9;--hdr:#e2e8f0;--txt:#1e293b;--dim:#64748b;--acc:#0284c7;--warn:#dc2626;--btn-bg:#cbd5e1;--btn-hover:#94a3b8;--sep:#cbd5e1}}}}
</style></head>
<body>
<div class="tbar">
  <span class="l">
    <span class="dot" id="dot"></span>
    <span class="port">{port_name}</span>
    <span class="baud">{baud}&nbsp;baud</span>
    <span class="sep"></span>
    <span class="count" id="info">{cnt}&nbsp;lines&nbsp;|&nbsp;{ts}</span>
  </span>
  <span class="r">
    <button class="btn" onclick="clearOutput()">Clear</button>
    <button class="btn danger" onclick="stopMonitor()">Stop</button>
  </span>
</div>
<div class="out" id="out">{rows}</div><!--/output-->
<div class="ftr">FirmForge Serial Monitor</div>
<script>
let cur=0,cleared=0,out=document.getElementById('out'),dot=document.getElementById('dot');
setInterval(function(){{
  var x=new XMLHttpRequest();
  x.open('GET',location.pathname.split('?')[0]+'?t='+Date.now(),true);
  x.onload=function(){{
    if(x.status!==200)return;
    var t=x.responseText,m=t.match(/<div class="out" id="out">([\\s\\S]*?)<!--\\/output-->/);
    if(!m)return;
    var n=(m[1].match(/<div class="line">/g)||[]).length;
    if(n!==cur){{cur=n;if(n>cleared){{out.innerHTML=m[1];var last=out.lastElementChild;if(last)last.scrollIntoView(false);}}}}
    var info=t.match(/<span[^>]+id="info"[^>]*>([^<]+)<\\/span>/);
    if(info)document.getElementById('info').innerHTML=info[1];
    var tm=t.match(/\| (\\d{{2}}:\\d{{2}}:\\d{{2}})<\\/span>/);
    if(tm){{var p=tm[1].split(':').map(Number),fs=p[0]*3600+p[1]*60+p[2],
      ns=new Date().getHours()*3600+new Date().getMinutes()*60+new Date().getSeconds(),
      df=Math.min(Math.abs(ns-fs),86400-Math.abs(ns-fs));
      dot.style.background=df<3?'var(--acc)':'var(--warn)';}}
  }};
  x.send();
}},500);
window.onload=function(){{var el=out.lastElementChild;if(el)el.scrollIntoView(false);}};
function clearOutput(){{cleared=cur;out.innerHTML='';cur=0;}}
function stopMonitor(){{fetch('/stop',{{method:'POST'}}).then(function(){{document.body.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100vh;font-size:15px;color:var(--dim)">Serial closed. You may close this page.</div>';}});}}
</script>
</body></html>"""

    try:
        os.makedirs(data_dir, exist_ok=True)
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception:
        pass


# ---------- Serial (ComPort context manager, same as S5) ----------
try:
    sys.path.insert(0, os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", ".."))
    from firmforge.providers.com_port import ComPort, com_port_clean_close

    # Retry open: avrdude may still be releasing COM4 after Flash
    ser_wrapper = None
    for _retry in range(10):
        try:
            ser_wrapper = ComPort(port_name, baud, timeout=0.3)
            ser_wrapper.__enter__()
            break
        except Exception:
            time.sleep(0.5)
    if ser_wrapper is None:
        raise RuntimeError(f"Failed to open {port_name} after 10 retries")

    # ser_wrapper._ser is the open Win32Serial object
    ser = ser_wrapper._ser
    time.sleep(2.0)
    try:
        ser.reset_input_buffer()
    except Exception:
        pass
    buf = ""
    _sample_written = False
    last_write = time.time()

    write_html()

    while True:
        if os.path.exists(stop_file):
            os._exit(0)
        if timeout_s > 0 and time.time() - _start_time > timeout_s:
            break

        # Write sample JSON when 3 lines collected or timeout
        if sample_path and not _sample_written:
            if len(lines) >= 3 or (time.time() - _start_time > _sample_timeout):
                try:
                    import json
                    os.makedirs(os.path.dirname(sample_path), exist_ok=True)
                    samples = lines[:3] if lines else []
                    with open(sample_path, "w") as f:
                        json.dump({"sample_lines": samples, "total": len(lines)}, f)
                except Exception:
                    pass
                _sample_written = True

        try:
            chunk = ser.read(64)
        except Exception:
            time.sleep(0.5)
            continue

        if chunk:
            if isinstance(chunk, bytes):
                chunk = chunk.decode("ascii", errors="replace")
            buf += chunk
            while chr(10) in buf:
                line, buf = buf.split(chr(10), 1)
                line = line.rstrip(chr(13))
                if line:
                    lines.append(line)
                    # unlimited

        now = time.time()
        if now - last_write >= 0.3:
            write_html()
            last_write = now

        time.sleep(0.05)

    ser_wrapper.__exit__(None, None, None)
    cleanup()

except Exception as e:
    try:
        import traceback
        with open(os.path.join(data_dir, "exit_trace.log"), "a") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] EXIT: CRASH {type(e).__name__}: {e}\n")
            f.write(traceback.format_exc())
    except Exception:
        pass
