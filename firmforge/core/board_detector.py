"""Board Detector -- USB/COM port scan and board identification.

规划 §2.9: 5-Stage Pipeline §1 (Detect).
Detection order (first match wins):
  1. AVR chip probe (avrdude signature read — hardware identity, most reliable)
  2. USB VID/PID scan (only official Arduino / ST-Link, not generic bridges)
  3. STM32 SWD probe (OpenOCD reads DBGMCU_IDCODE through CMSIS-DAP / ST-Link)
  4. Workspace inference (source code register analysis — no hardware needed)
  5. User text analysis (keyword match from natural language description)

CH340/CP210x/FT232 are explicitly excluded: they're USB-TTL bridges,
not board identifiers, and carry no MCU identity information.

STM32 needs its own probe rather than a VID/PID entry: a CMSIS-DAP adapter
is an HID device with **no COM port**, so the COM-port scan can never see it
(the historic failure was "add 0D28:0204 to the VID/PID table" — that entry
could never be reached). And an adapter being present says nothing about the
board: it only proves a debugger is plugged in.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# Known USB VID/PID to board mapping (expandable)
# Format: {(vid_hex, pid_hex): (board_id, confidence)}
# RULE: Only board-specific VID/PID pairs.  Never map generic USB-TTL chips
# (CH340, CP210x, FT232, etc.) — those are bridges, not board identifiers.
_KNOWN_DEVICES: dict[tuple[int, int], tuple[str, float]] = {
    # Arduino official (VID=0x2341 for Arduino LLC)
    (0x2341, 0x0042): ("arduino_mega", 0.95),       # Arduino Mega 2560 R3
    (0x2341, 0x0010): ("arduino_mega", 0.95),        # Arduino Mega 2560 (old)
    (0x2341, 0x0043): ("arduino_328p", 0.95),         # Arduino Uno R3
    (0x2341, 0x0001): ("arduino_328p", 0.95),         # Arduino Uno (old bootloader)
    # Arduino clone VID/PID (varies by manufacturer)
    (0x2A03, 0x0042): ("arduino_mega", 0.85),        # Arduino Mega 2560 clone
    (0x2A03, 0x0001): ("arduino_328p", 0.85),         # Arduino Uno clone
}


@dataclass
class BoardCandidate:
    """A candidate board match from detection sources."""
    board_id: str
    source: str          # "usb_vidpid" | "workspace" | "schematic" | "user_input"
    confidence: float    # 0.0 - 1.0
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DetectionResult:
    """Aggregated detection result for board routing."""
    board_id: str | None = None
    boards: list[str] = field(default_factory=list)  # all detected board IDs (multi-board)
    candidates: list[BoardCandidate] = field(default_factory=list)
    asked_user: bool = False
    user_confirmed: bool = False
    #: 探测过程中的异常说明（探针在位但目标无响应、DEV_ID 与声明不符…）。
    #: 与 candidates 分开存放：这些不是候选，是「哪些结论现在不能下」。
    notes: list[str] = field(default_factory=list)


class BoardDetector:
    """Multi-source board detector for 5-Stage Pipeline §1.

    Usage:
        detector = BoardDetector(boards_dir=Path("./boards"))
        result = detector.detect()

        if result.board_id:
            print(f"Detected: {result.board_id}")
        elif not result.asked_user:
            # Need to ask user
            result = detector.ask_user_board()
    """

    def __init__(
        self,
        boards_dir: Path | str | None = None,
        known_devices: dict | None = None,
    ) -> None:
        from firmforge.core.resources import boards_dir as _default_boards
        self._boards_dir = Path(boards_dir) if boards_dir else _default_boards()
        self._known_devices = known_devices or _KNOWN_DEVICES

    def detect(
        self,
        workspace_dir: Path | None = None,
        source_dir: Path | None = None,
        user_text: str = "",
    ) -> DetectionResult:
        """Run all available detection sources and fuse results.

        Detection order (first match wins):
          1. AVR chip probe (avrdude signature read — hardware identity, most reliable)
          2. USB VID/PID scan (only official Arduino / ST-Link, not generic bridges)
          3. Workspace inference (source code register analysis — no hardware needed)
          4. User text analysis (keyword match from natural language description)
        """
        result = DetectionResult()

        # Source 1: USB VID/PID scan (gather COM ports for probe chain)
        usb_candidates = self._scan_usb()
        if usb_candidates:
            result.candidates.extend(usb_candidates)

        # Source 2: AVR chip probe (reads signature via avrdude)
        # This is the most reliable detection: directly asks the MCU "who are you?"
        avr_candidates = self._probe_avr(usb_candidates)
        if avr_candidates:
            result.candidates.extend(avr_candidates)

        # Fuse: AVR chip probe is authoritative (reads actual MCU signature bytes).
        # USB VID/PID is only a fallback for boards that can't be probed.
        if result.candidates:
            # Collect ALL unique AVR probe matches (across all ports)
            avr_found: dict[str, BoardCandidate] = {}
            for c in result.candidates:
                if c.source.startswith("avr_probe"):
                    bid = c.board_id
                    # Keep highest confidence per board type
                    if bid not in avr_found or c.confidence > avr_found[bid].confidence:
                        avr_found[bid] = c

            if avr_found:
                detected_boards = list(avr_found.keys())
                result.boards = detected_boards
                if len(detected_boards) == 1:
                    # Single board detected — auto-select
                    only = detected_boards[0]
                    result.board_id = only
                    cand = avr_found[only]
                    logger.info("Detected: %s via AVR probe (%.0f%%)",
                                only, cand.confidence * 100)
                    return result
                else:
                    # Multiple distinct boards detected — return all,
                    # let caller (CLI/MCP/pipeline) handle disambiguation
                    result.candidates = list(avr_found.values())
                    logger.info("Detected %d boards: %s",
                                len(detected_boards), ", ".join(detected_boards))
                    return result

            # Priority 2: USB VID/PID (only for boards with unique IDs)
            usb_cand = next((c for c in result.candidates
                             if c.source == "usb_vidpid" and c.confidence >= 0.90), None)
            if usb_cand:
                result.board_id = usb_cand.board_id
                result.boards = [usb_cand.board_id]
                logger.info("Detected: %s via USB VID/PID (%.0f%%)",
                            usb_cand.board_id, usb_cand.confidence * 100)
                return result

        # --- Source 3: STM32 SWD probe (CMSIS-DAP / ST-Link) ---
        # 只在 AVR 与 USB 都没给出结论时才试。detect 是流水线 S1 的必经步骤：
        # AVR 板插着时不该为 SWD 多付一次 OpenOCD 启动（约 1 s），
        # 而两块板同时插着本来就该由调用方显式指定板卡。
        swd_candidates, swd_notes = self._probe_stm32()
        result.notes.extend(swd_notes)
        if swd_candidates:
            result.candidates.extend(swd_candidates)
            result.boards = [c.board_id for c in swd_candidates]
            if len(swd_candidates) == 1:
                result.board_id = swd_candidates[0].board_id
                logger.info("Detected: %s via SWD probe (%.0f%%)",
                            result.board_id, swd_candidates[0].confidence * 100)
            return result

        # --- Fallback: no hardware detection succeeded ---
        # Try workspace inference (source code analysis, board.json lookup)
        ws_candidate = self._infer_from_workspace(
            workspace_dir=workspace_dir,
            source_dir=source_dir,
        )
        if ws_candidate:
            result.candidates.append(ws_candidate)
            result.board_id = ws_candidate.board_id
            result.boards = [ws_candidate.board_id]
            logger.info("Detected: %s via workspace inference (%.0f%%)",
                        ws_candidate.board_id, ws_candidate.confidence * 100)
            return result

        # User text analysis (lowest confidence, last resort)
        if user_text:
            txt = self._extract_board_from_text(user_text)
            if txt:
                result.candidates.append(txt)
                result.board_id = txt.board_id
                result.boards = [txt.board_id]
                logger.info("Detected: %s via user description (%.0f%%)",
                            txt.board_id, txt.confidence * 100)
                return result

        return result

    def ask_user_board(self, candidates: list[BoardCandidate] | None = None,
                       boards_dir: Path | None = None) -> DetectionResult:
        """Generate a list of board options for user selection.

        In automated mode, this returns a DetectionResult with board_id=None
        and asked_user=True, signaling the CLI to prompt the user.

        Returns sorted candidates for display.
        """
        result = DetectionResult(asked_user=True)
        if candidates:
            result.candidates = sorted(candidates,
                                       key=lambda c: c.confidence, reverse=True)
        return result

    def resolve_board(
        self,
        board_id: str,
        boards_dir: Path | None = None,
    ) -> dict[str, Any] | None:
        """Resolve board_id to board definition (board.yaml or board.json).

        **`board_id` 的唯一注入点。** 项目约定：**目录名即板卡身份** ——
        板卡文件自身不声明 `board_id`（三个板卡一致）。在这里注入，使得
        「配置知道自己是谁」成为不变量，而非调用方需要记得做的事：
        管道 S1/S3/S4/S5、CLI、MCP 拿到的都直接可用。

        此前只有 `_stage_detect` 注入过，而 S3/S4/S5 各自重新调用本方法，
        注入随即丢失 —— STM32 的板级文件定位（`.ld` / `hal_conf.h` /
        `include/`）因此拿到 `None`，错误一路拖到编译器才暴露。
        """
        bd = Path(boards_dir or self._boards_dir)
        for filename in ("board.yaml", "board.json"):
            board_path = bd / board_id / filename
            if board_path.exists():
                config = self._load_board_file(board_path)
                if isinstance(config, dict):
                    config["board_id"] = board_id
                return config
        logger.warning("board.yaml/board.json not found for %s at %s",
                       board_id, bd / board_id)
        return None

    def list_available_boards(self, boards_dir: Path | None = None) -> list[str]:
        """List all board IDs with board.yaml or board.json in the boards/ directory."""
        bd = Path(boards_dir or self._boards_dir)
        boards: list[str] = []
        if bd.is_dir():
            for entry in sorted(bd.iterdir()):
                if entry.is_dir() and (
                    (entry / "board.yaml").exists() or (entry / "board.json").exists()
                ):
                    boards.append(entry.name)
        return boards

    # -- Source implementations --

    def _scan_usb(self) -> list[BoardCandidate]:
        """Scan USB/COM ports and match against VID/PID table.

        端口枚举走 `providers/win32ports.py`（Win32 SetupAPI），**不碰 pyserial**：
        在 Win11 + CH340 上，pyserial 的 list_ports 会留下 stale 驱动状态，
        之后连 avrdude 都打不开端口。
        Returns candidates sorted by confidence (descending).
        """
        candidates: list[BoardCandidate] = []

        try:
            from firmforge.providers.win32ports import list_ports
        except Exception as e:
            logger.warning("COM port enumeration unavailable: %s", e)
            return candidates

        ports = list_ports()
        for port in ports:
            if port.vid is None or port.pid is None:
                continue

            key = (port.vid, port.pid)
            if key in self._known_devices:
                board_id, confidence = self._known_devices[key]
                candidates.append(BoardCandidate(
                    board_id=board_id,
                    source="usb_vidpid",
                    confidence=confidence,
                    details={
                        "vid": f"0x{port.vid:04X}",
                        "pid": f"0x{port.pid:04X}",
                        "port": port.device,
                        "description": port.description,
                        "serial_number": port.serial_number,
                        "manufacturer": port.manufacturer,
                    },
                ))
                logger.info("USB match: %s → %s (%.0f%%)",
                            port.device, board_id, confidence * 100)

        # Sort by confidence descending
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    def _scan_workspace(self, workspace_dir: Path) -> BoardCandidate | None:
        """P2: Scan workspace for board.yaml/board.json or project files."""
        for filename in ("board.yaml", "board.json"):
            board_path = workspace_dir / filename
            if board_path.exists():
                try:
                    config = self._load_board_file(board_path)
                    board_id = config.get("board_name", "").lower().replace(" ", "_")
                    return BoardCandidate(
                        board_id=board_id,
                        source="workspace",
                        confidence=0.85,
                        details={"path": str(board_path)},
                    )
                except Exception:
                    pass
        return None

    @staticmethod
    def _load_board_file(path: Path) -> dict[str, Any]:
        """Load board definition from .yaml or .json."""
        if path.suffix == ".yaml":
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _infer_from_workspace(
        self,
        workspace_dir: Path | None = None,
        source_dir: Path | None = None,
    ) -> BoardCandidate | None:
        """Fallback: infer board from workspace configuration and source code.

        When no hardware probe succeeds, try to determine the target board
        from workspace clues, in priority order:
          1. Explicit board.json in the project root
          2. Source code register names (DDRB, UCSR0A, etc.) → chip family

        Returns None if no inference is possible.
        """
        # Priority 1: explicit board.json in workspace root
        if workspace_dir:
            ws = self._scan_workspace(workspace_dir)
            if ws:
                return ws

        # Priority 2: source code register analysis
        if source_dir and source_dir.is_dir():
            return self._infer_from_source(source_dir)

        return None

    def _infer_from_source(
        self, source_dir: Path,
    ) -> BoardCandidate | None:
        """Infer chip family from source code register usage.

        Scans .c/.cpp/.ino files for AVR-specific register names.
        Returns a low-confidence candidate (0.60) to avoid false positives.
        """
        avr_regs = ["DDRA", "DDRB", "DDRC", "DDRD", "DDRE", "DDRF", "DDRG",
                     "DDRH", "DDRJ", "DDRK", "DDRL",
                     "PORTA", "PORTB", "PORTC", "PORTD", "PORTE", "PORTF",
                     "PORTG", "PORTH", "PORTJ", "PORTK", "PORTL",
                     "PINA", "PINB", "PINC", "PIND", "PINE", "PINF",
                     "PING", "PINH", "PINJ", "PINK", "PINL",
                     "UCSR0A", "UCSR0B", "UCSR0C",
                     "UCSR1A", "UCSR1B", "UCSR1C",
                     "UBRR0", "UBRR1", "UBRR0H", "UBRR0L",
                     "ADMUX", "ADCSRA", "ADCSRB", "ADCH", "ADCL",
                     "TCCR0A", "TCCR0B", "TCCR1A", "TCCR1B", "TCCR1C",
                     "TCCR2A", "TCCR2B",
                     "TCCR3A", "TCCR3B", "TCCR3C",
                     "TCCR4A", "TCCR4B", "TCCR4C",
                     "TCCR5A", "TCCR5B", "TCCR5C",
                     "SPCR", "SPSR", "SPDR",
                     "TWCR", "TWBR", "TWSR", "TWDR",
                     "EECR", "EEDR", "EEAR", "EEARH", "EEARL",
                     "WDTCR", "WDTCSR", "CLKPR", "MCUCR", "MCUSR",
                     "SREG", "SPH", "SPL", "PCMSK0", "PCMSK1", "PCMSK2",
                     "EIMSK", "EICRA", "EICRB",
                     "ASSR", "OCR0A", "OCR0B",
                     "OCR1A", "OCR1B", "OCR1C",
                     "OCR2A", "OCR2B",
                     "OCR3A", "OCR3B", "OCR3C",
                     "OCR4A", "OCR4B", "OCR4C",
                     "OCR5A", "OCR5B", "OCR5C",
                     "ICR1", "ICR3", "ICR4", "ICR5",
                     "TCNT0", "TCNT1", "TCNT1H", "TCNT1L",
                     "TCNT2", "TCNT3", "TCNT4", "TCNT5",
                     "GTCCR", "DIDR0", "DIDR1", "DIDR2",
                     "PRR0", "PRR1",
                     "TIMSK0", "TIMSK1", "TIMSK2", "TIMSK3", "TIMSK4", "TIMSK5",
                     "TIFR0", "TIFR1", "TIFR2", "TIFR3", "TIFR4", "TIFR5",
                     ]
        mega_only = ["DDRE", "DDRF", "DDRG", "DDRH", "DDRJ", "DDRK", "DDRL",
                      "PORTE", "PORTF", "PORTG", "PORTH", "PORTJ", "PORTK", "PORTL",
                      "PINE", "PINF", "PING", "PINH", "PINJ", "PINK", "PINL",
                      "UCSR1A", "UCSR1B", "UCSR1C", "UBRR1",
                      "TCCR3A", "TCCR3B", "TCCR3C",
                      "TCCR4A", "TCCR4B", "TCCR4C",
                      "TCCR5A", "TCCR5B", "TCCR5C",
                      "OCR3A", "OCR3B", "OCR3C",
                      "OCR4A", "OCR4B", "OCR4C",
                      "OCR5A", "OCR5B", "OCR5C",
                      "ICR3", "ICR4", "ICR5",
                      "TCNT3", "TCNT4", "TCNT5",
                      "TIMSK3", "TIMSK4", "TIMSK5",
                      "TIFR3", "TIFR4", "TIFR5",
                      "PCMSK2",
                      "EICRB",
                      "PRR1",
                      ]
        found_avr = set()
        found_mega = set()

        try:
            for fpath in source_dir.rglob("*"):
                if fpath.suffix not in (".c", ".cpp", ".h", ".ino", ".hpp"):
                    continue
                try:
                    text = fpath.read_text("utf-8", errors="replace")
                except Exception:
                    continue
                for reg in avr_regs:
                    if reg in text:
                        found_avr.add(reg)
                for reg in mega_only:
                    if reg in text:
                        found_mega.add(reg)
        except Exception:
            pass

        # AVR match: use mega-only registers to distinguish 2560 vs 328P
        if found_avr:
            board_id = "arduino_mega" if len(found_mega) >= 2 else "arduino_328p"
            return BoardCandidate(
                board_id=board_id,
                source="workspace_source",
                confidence=0.60,
                details={
                    "matched_registers": list(found_avr)[:10],
                    "mega_specific": list(found_mega)[:5],
                },
            )

        return None

    @staticmethod
    def _extract_board_from_text(text: str) -> BoardCandidate | None:
        """P2: Use LLM to extract board info from natural language."""
        # MVP: simple keyword match
        text_lower = text.lower()
        board_map = {
            "arduino mega": ("arduino_mega", 0.70),
            "mega2560": ("arduino_mega", 0.75),
            "mega 2560": ("arduino_mega", 0.75),
            "arduino uno": ("arduino_328p", 0.80),
            "uno r3": ("arduino_328p", 0.80),
            "arduino nano": ("arduino_328p", 0.75),
            "arduino 328p": ("arduino_328p", 0.85),
            "atmega328p": ("arduino_328p", 0.85),
        }
        for keyword, (board_id, confidence) in board_map.items():
            if keyword in text_lower:
                return BoardCandidate(
                    board_id=board_id,
                    source="user_input",
                    confidence=confidence,
                    details={"keyword": keyword},
                )
        return None

    # -- AVR chip probe: read MCU signature via avrdude --

    # AVR signature bytes → (chip_name, board_id, confidence)
    _AVR_SIGNATURES: dict[str, tuple[str, str, float]] = {
        "1e9801": ("ATmega2560", "arduino_mega", 0.95),
        "1e950f": ("ATmega328P", "arduino_328p", 0.95),
        "1e9514": ("ATmega328", "arduino_328p", 0.90),
        "1e9516": ("ATmega168", "arduino_328p", 0.85),
    }

    def _probe_avr(
        self, usb_candidates: list[BoardCandidate],
    ) -> list[BoardCandidate]:
        """Probe COM ports with avrdude to read AVR chip signature.

        Uses appropriate programmer for each MCU part:
          - m2560 → wiring (STK500v2 protocol)
          - m328p → arduino (STK500v1 with auto DTR reset)
        """
        import subprocess

        # Resolve avrdude path
        try:
            from firmforge.providers.arduino.toolchain import resolve_toolchain
            tc = resolve_toolchain()
            avrdude = tc.avrdude
            avrdude_conf = tc.avrdude_conf
        except Exception:
            logger.debug("AVR probe: avrdude not found, skipping")
            return []

        if not avrdude or not Path(avrdude).exists():
            return []

        # Enumerate COM ports — skip virtual/simulation ports
        # 用 Win32 SetupAPI 枚举（win32ports），不用 pyserial：后者的 list_ports
        # 在 Win11 + CH340 上会污染驱动状态。
        com_ports: list[str] = []
        try:
            from firmforge.providers.win32ports import list_ports
            for port_info in list_ports():
                if not (port_info.device and port_info.device.upper().startswith("COM")):
                    continue
                # Skip virtual/simulation ports (ELTIMA, com0com, etc.)
                desc = (port_info.description or "").lower()
                if "virtual" in desc or "eltima" in desc:
                    continue
                com_ports.append(port_info.device)
        except Exception as e:
            logger.debug("COM port enumeration failed: %s", e)

        # Also include ports from USB candidates (official Arduino VID/PID)
        for c in usb_candidates:
            port = c.details.get("port", "")
            if port and port.upper().startswith("COM") and port not in com_ports:
                com_ports.append(port)

        if not com_ports:
            return []

        results: list[BoardCandidate] = []

        # Probe order: m328p (arduino, auto DTR) first, then m2560 (wiring).
        # -c arduino handles its own DTR reset on port open — no Python
        # serial workarounds needed. CH340 4.0 compatibility is avrdude's job.
        probe_parts = [("m328p", "arduino"), ("m2560", "wiring")]

        # Resilient baud fallback: 115200 (Optiboot) then 57600 (old Nano bootloader)
        baud_rates = [115200, 57600]

        for port in com_ports:
            # CH340 driver leaves stale port state after pyserial list_ports.
            # A clean close resets the driver state so avrdude can open the port.
            # This does NOT trigger DTR reset — avrdude -c arduino handles that.
            try:
                from firmforge.providers.com_port import com_port_clean_close
                com_port_clean_close(port)
            except Exception:
                pass

            for part, programmer in probe_parts:
                for baud in baud_rates:
                    cmd = [avrdude] + [
                        "-c", programmer,
                        "-p", part,
                        "-P", port,
                        "-b", str(baud),
                        "-q", "-q",
                    ]

                    try:
                        r = subprocess.run(
                            cmd,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE,
                            timeout=2,
                        )
                    except subprocess.TimeoutExpired:
                        continue
                    except OSError:
                        continue

                    if r.returncode != 0:
                        continue
                    # Decode stderr only (avrdude writes to stderr)
                    try:
                        output = r.stderr.decode("utf-8", errors="replace").lower()
                    except Exception:
                        continue

                    # avrdude exit 0 = signature matched + bootloader responded
                    if "does not match" in output:
                        import re
                        sig_match = re.search(
                            r'signature\s*=\s*0x([0-9a-f]{6})', output,
                        )
                        if sig_match:
                            sig = sig_match.group(1)
                            sig_entry = self._AVR_SIGNATURES.get(sig)
                            if sig_entry:
                                chip_name, board_id, confidence = sig_entry
                                results.append(BoardCandidate(
                                    board_id=board_id,
                                    source=f"avr_probe:{port}",
                                    confidence=confidence,
                                    details={
                                        "chip": chip_name,
                                        "signature": f"0x{sig}",
                                        "port": port,
                                        "bootloader": "wiring",
                                    },
                                ))
                        continue

                    # Signature matched expected MCU
                    if "m2560" in part:
                        results.append(BoardCandidate(
                            board_id="arduino_mega", source=f"avr_probe:{port}",
                            confidence=0.95,
                            details={"chip": "ATmega2560", "signature": "0x1e9801",
                                     "port": port, "bootloader": "wiring"},
                        ))
                    elif "m328p" in part:
                        results.append(BoardCandidate(
                            board_id="arduino_328p", source=f"avr_probe:{port}",
                            confidence=0.95,
                            details={"chip": "ATmega328P", "signature": "0x1e950f",
                                     "port": port, "bootloader": "wiring"},
                        ))
                    break  # Found match on baud/part, stop baud loop

        return results

    # =====================================================================
    # STM32 SWD probe — read DBGMCU_IDCODE through the debug adapter
    # =====================================================================

    #: DBGMCU_IDCODE 的绝对地址。DBGMCU_BASE = 0x5C001000、IDCODE 偏移 0x00，
    #: 依据厂商头文件 stm32h743xx.h。实测 `mrw 0x5C001000` → 0x20036450
    #: （REV_ID=0x2003 = Rev V、DEV_ID=0x450），与丝印和 DBGMCU 双确认一致。
    #: 知识库里**没有** DBGMCU 外设（128 个组里没有），所以这个值只能内置。
    _STM32_IDCODE_ADDR = 0x5C001000

    def _stm32_boards(self) -> list[tuple[str, dict[str, Any]]]:
        """列出 boards_dir 里所有 `platform: stm32` 的板卡声明。

        按路径排序，保证多板时输出顺序可复现；`board_id` 缺省取目录名
        （board.yaml 顶层只有 board_name，没有 board_id）。
        """
        out: list[tuple[str, dict[str, Any]]] = []
        for path in sorted(self._boards_dir.glob("*/board.yaml")):
            try:
                cfg = self._load_board_file(path) or {}
            except Exception as exc:        # noqa: BLE001
                logger.debug("跳过 %s: %s", path, exc)
                continue
            if str(cfg.get("platform") or "").lower() != "stm32":
                continue
            out.append((cfg.get("board_id") or path.parent.name, cfg))
        return out

    def _probe_stm32(self) -> tuple[list[BoardCandidate], list[str]]:
        """用 SWD 探针读 `DBGMCU_IDCODE`，与 `board.yaml::mcu.dev_id` 比对。

        为什么不是往 VID/PID 表里加一条
        ---------------------------------
        CMSIS-DAP 是 **HID 设备、没有 COM 口**，而 `_scan_usb()` 只枚举
        COM 口，所以 (0x0D28, 0x0204) 这条表项永远不会被命中 —— 这正是
        "ff detect 认不到 DAPLink" 的真实原因（不是表里缺一行）。
        而且探针在位只证明"插了个调试器"，不证明目标板是什么；
        只有读到芯片自己吐的 IDCODE 才算硬件身份证据。

        为什么置信度 0.85 而不是 AVR 的 0.95
        ------------------------------------
        DEV_ID 只能定到**系列**：H742/H743/H753/H750 同为 0x450，无法区分
        具体型号。所以"认出 gc_h743"实际依赖两个前提：① 探针连得上目标；
        ② 注册表里只有一块声明了该 DEV_ID 的板卡。第二个前提一旦被打破
        （以后再添一块 H7 板卡），这里返回多候选、交给调用方指定 —— 不猜。

        副作用：halt → 读 → resume，目标被暂停约 200 ms。与 avrdude probe
        会复位 AVR 板属同一类副作用，都发生在"我要用这块板"的语义下。
        """
        boards = self._stm32_boards()
        if not boards:
            return [], []

        try:
            from firmforge.providers.stm32.debug import run_script
            from firmforge.providers.stm32.toolchain import resolve_toolchain
        except Exception as exc:            # noqa: BLE001
            logger.debug("STM32 探针模块不可用: %s", exc)
            return [], []

        tc = resolve_toolchain()
        if [p for p in tc.problems() if "openocd" in p or "scripts" in p]:
            # 没装 OpenOCD 不是"检测失败"，是这条路没配 —— 静默跳过，
            # 否则每次 detect 都多一条与用户无关的告警。
            logger.debug("STM32 探针跳过：OpenOCD 未就绪")
            return [], []

        # 只读一个寄存器，但必须先 halt（Cortex-M 在 running 态读内存会失败）。
        # 结尾 resume 把 CPU 放回去；FF_DONE 标记保证会话完整（见 debug.py）。
        # 🔴 `shutdown` 必须自己写：run_script 只负责把脚本跑完，不会替你退出。
        #    少了它，openocd 执行完脚本会进入交互模式等 stdin，一路挂到超时
        #    —— 表现为"探针未连接或目标未上电"，与真实原因（脚本没退出）无关。
        script = "\n".join([
            'if {[catch {init} _e]} { echo "FF_INIT=ERR"; echo FF_DONE=1; shutdown; return }',
            'if {[catch {halt} _e]} { echo "FF_HALT=ERR" } else { echo "FF_HALT=OK" }',
            "set ff_id NA",
            f"if {{[catch {{set ff_id [mrw 0x{self._STM32_IDCODE_ADDR:08X}]}} _e] == 0}} {{",
            '    echo "FF_IDCODE=$ff_id"',
            "}",
            "catch {resume} _e",
            "echo FF_DONE=1",
            "shutdown",
        ])

        candidates: list[BoardCandidate] = []
        notes: list[str] = []
        for board_id, cfg in boards:
            run = run_script(script, board_config=cfg, toolchain=tc, timeout=15.0)
            idcode = _parse_idcode(run.text)
            if idcode is None:
                if _probe_absent(run.text):
                    logger.debug("SWD: 未找到调试探针（%s）", board_id)
                    continue
                # 探针在、但目标没响应 —— 这是值得报告的信息：
                # 与"没有探针"处置不同（一个查供电/接线，一个什么都不用做）。
                detail = run.error or _swd_error(run.text) or "未读到 DBGMCU_IDCODE"
                notes.append(f"SWD 探测 {board_id} 失败：{detail}")
                continue

            dev_id = idcode & 0xFFF
            rev_id = (idcode >> 16) & 0xFFFF
            declared = _as_int((cfg.get("mcu") or {}).get("dev_id"))
            if declared is not None and declared != dev_id:
                notes.append(
                    f"SWD 读到 DEV_ID=0x{dev_id:03X}，与 {board_id} 声明的 "
                    f"0x{declared:03X} 不符 —— 探针连的是另一颗芯片"
                )
                continue

            candidates.append(BoardCandidate(
                board_id=board_id,
                source="swd_probe",
                confidence=0.85,
                details={
                    "dev_id": f"0x{dev_id:03X}",
                    "rev_id": f"0x{rev_id:04X}",
                    "probe": _probe_name(run.text),
                    "elapsed_ms": round(run.elapsed_ms),
                },
            ))
            logger.info("SWD probe: %s → DEV_ID=0x%03X REV_ID=0x%04X",
                        board_id, dev_id, rev_id)

        return candidates, notes

    # =====================================================================
    # Serial Bootloader Reset — DTR 1200 baud toggle for avrdude
    # =====================================================================

    @staticmethod
    def reset_to_bootloader(port: str) -> None:
        """Toggle DTR at 1200 baud to enter Arduino bootloader mode.

        Uses ComPort (pyserial + Win32Serial fallback) to handle
        CH340 3.9/4.0 drivers. 1.5s delay ensures bootloader is ready.
        If already in bootloader, this is a harmless no-op.
        """
        try:
            from firmforge.providers.com_port import ComPort
            import time
            with ComPort(port, 1200, timeout=0.5):
                time.sleep(0.1)
            time.sleep(1.5)  # Wait for bootloader to enumerate and stabilize
        except Exception:
            pass


# ---------------------------------------------------------------------------
# SWD 探测的解析辅助函数
# ---------------------------------------------------------------------------

def _parse_idcode(text: str) -> int | None:
    """从 OpenOCD 输出里取 `FF_IDCODE=<值>` 标记的值。

    走标记而不是匹配 openocd 的内存打印格式：`mrw` 在命令行返回裸值、
    在 `-f` 脚本里走 `echo`，两种输出的格式都不该由调用方去猜。
    """
    m = re.search(r"FF_IDCODE=(0x[0-9a-fA-F]+|\d+)", text or "")
    if not m:
        return None
    try:
        return int(m.group(1), 0)
    except ValueError:
        return None


def _probe_absent(text: str) -> bool:
    """输出表明「根本没有调试探针」，而不是「探针在但目标没响应」。

    两者处置完全不同：没探针 = 这条路不适用（静默跳过，别报噪声）；
    有探针但连不上目标 = 值得报告（去查目标供电、SWD 接线、复位）。
    合并成一句"检测失败"会把后者也变成噪声，人就不看了。
    """
    t = (text or "").lower()
    return any((
        "unable to find a matching cmsis-dap" in t,
        "unable to find a matching st-link" in t,
        "no cmsis-dap device" in t,
        "no st-link device" in t,
        "could not find a matching" in t,
    ))


def _swd_error(text: str) -> str:
    """取 OpenOCD 输出里第一条有内容的 `Error:` 行，作为失败原因。

    `init` 失败时会话仍会正常收尾（脚本里 catch 住了），所以 run.error 是空的，
    真实原因只在输出里。不把这句话带出来，调用方看到的就只有
    "未读到 DBGMCU_IDCODE" —— 等于没说。
    """
    for raw in (text or "").splitlines():
        line = raw.strip()
        if line.startswith("Error:") and len(line.strip()) > len("Error:"):
            return line[len("Error:"):].strip()
    return ""


def _probe_name(text: str) -> str | None:
    """从 OpenOCD 开场日志里取探针标识（CMSIS-DAP 的 Serial# 或 ST-Link）。"""
    m = re.search(r"CMSIS-DAP:\s*Serial#\s*=\s*(\S+)", text or "")
    if m:
        return f"CMSIS-DAP {m.group(1)}"
    if "ST-Link" in (text or ""):
        return "ST-Link"
    return None


def _as_int(value: Any) -> int | None:
    """把 board.yaml 里的 `"0x450"` / `1104` 统一成 int；读不出返回 None。"""
    if value is None:
        return None
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None
