"""Board Detector -- USB/COM port scan and board identification.

规划 §2.9: 5-Stage Pipeline §1 (Detect).
Detection order (first match wins):
  1. AVR chip probe (avrdude signature read — hardware identity, most reliable)
  2. USB VID/PID scan (only official Arduino / ST-Link, not generic bridges)
  3. Workspace inference (source code register analysis — no hardware needed)
  4. User text analysis (keyword match from natural language description)

CH340/CP210x/FT232 are explicitly excluded: they're USB-TTL bridges,
not board identifiers, and carry no MCU identity information.
"""

from __future__ import annotations

import json
import logging
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
        """Resolve board_id to board definition (board.yaml or board.json)."""
        bd = Path(boards_dir or self._boards_dir)
        for filename in ("board.yaml", "board.json"):
            board_path = bd / board_id / filename
            if board_path.exists():
                return self._load_board_file(board_path)
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

        Uses pyserial to enumerate available ports.
        Returns candidates sorted by confidence (descending).
        """
        candidates: list[BoardCandidate] = []

        try:
            import serial.tools.list_ports
        except ImportError:
            logger.warning("pyserial not installed; USB detection disabled")
            return candidates

        ports = list(serial.tools.list_ports.comports())
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
        com_ports: list[str] = []
        try:
            import serial.tools.list_ports
            for port_info in serial.tools.list_ports.comports():
                if not (port_info.device and port_info.device.upper().startswith("COM")):
                    continue
                # Skip virtual/simulation ports (ELTIMA, com0com, etc.)
                desc = (port_info.description or "").lower()
                if "virtual" in desc or "elTIMA" in desc.lower():
                    continue
                com_ports.append(port_info.device)
        except ImportError:
            pass

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
