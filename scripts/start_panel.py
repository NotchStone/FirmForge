import sys, time, json
from pathlib import Path
sys.path.insert(0, r"C:/MyLab/MCU")
from firmforge.core.pipeline_runner import PipelineRunner, PipelineStage

r = PipelineRunner(boards_dir="boards", workspace=".")

t0 = time.time()
det = r.detect()
det_ms = (time.time() - t0) * 1000
board_id = det.get("board_id") or "arduino_328p"
stages = [PipelineStage(1, "Detect", True, det_ms, {"board": board_id}, None)]

state = {}
try:
    state = json.loads(Path(".firmforge/state.json").read_text(encoding="utf-8"))
except Exception:
    pass
stg = state.get("stages", {})
for num, name, key in [(2, "Review", "review"), (3, "Build", "build"), (4, "Flash", "flash")]:
    if stg.get(key, {}).get("status") == "done":
        stages.append(PipelineStage(num, name, True, 0, {}, None))
stages.append(PipelineStage(5, "Verify", True, 0, {}, None))
stages_html, process_html = r._build_summary(stages)

print("PANEL_START board=%s" % board_id, flush=True)
s5 = r._stage_verify(board_id, "", stages_summary=stages_html, process_summary=process_html)
print("VERIFY:", s5.success, s5.details.get("sample_lines", []), flush=True)
while getattr(r, '_collector_alive', None) and r._collector_alive.is_alive():
    time.sleep(1)
