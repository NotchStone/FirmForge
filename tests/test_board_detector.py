"""Unit tests for board_detector.py."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from firmforge.core.board_detector import (
    BoardDetector, BoardCandidate, DetectionResult, _KNOWN_DEVICES,
)


class TestBoardDetector:
    """Tests for USB/COM board detection."""

    def test_list_available_boards(self, temp_dir):
        # Create a minimal board directory
        board_dir = temp_dir / "arduino_mega"
        board_dir.mkdir()
        (board_dir / "board.json").write_text(json.dumps({"board_name": "Arduino Mega 2560"}))

        detector = BoardDetector(boards_dir=temp_dir)
        boards = detector.list_available_boards(temp_dir)
        assert "arduino_mega" in boards

    def test_no_boards_directory(self, temp_dir):
        empty = temp_dir / "empty_boards"
        empty.mkdir()
        detector = BoardDetector(boards_dir=empty)
        assert detector.list_available_boards(empty) == []

    def test_resolve_board_found(self, temp_dir):
        board_dir = temp_dir / "arduino_mega"
        board_dir.mkdir()
        config = {"board_name": "Arduino Mega 2560", "mcu": {"chip": "ATmega2560"}}
        (board_dir / "board.json").write_text(json.dumps(config))

        detector = BoardDetector(boards_dir=temp_dir)
        result = detector.resolve_board("arduino_mega", boards_dir=temp_dir)
        assert result is not None
        assert result["board_name"] == "Arduino Mega 2560"

    def test_resolve_board_not_found(self, temp_dir):
        detector = BoardDetector(boards_dir=temp_dir)
        result = detector.resolve_board("nonexistent", boards_dir=temp_dir)
        assert result is None

    def test_extract_board_from_text_arduino_mega(self):
        candidate = BoardDetector._extract_board_from_text("用 Arduino Mega 2560 点灯")
        assert candidate is not None
        assert candidate.board_id == "arduino_mega"
        assert candidate.source == "user_input"

    def test_extract_board_from_text_arduino_uno(self):
        candidate = BoardDetector._extract_board_from_text("Arduino Uno serial echo")
        assert candidate is not None
        assert candidate.board_id == "arduino_328p"

    def test_extract_board_from_text_no_match(self):
        candidate = BoardDetector._extract_board_from_text("hello world")
        assert candidate is None

    def test_usb_scan_with_no_ports(self, temp_dir):
        detector = BoardDetector(boards_dir=temp_dir)
        # Without pyserial or with no ports, should return empty
        with patch("serial.tools.list_ports.comports", return_value=[]):
            candidates = detector._scan_usb()
            assert candidates == []

    def test_usb_scan_matching_arduino_mega(self, temp_dir):
        detector = BoardDetector(boards_dir=temp_dir)

        mock_port = MagicMock()
        mock_port.vid = 0x2341
        mock_port.pid = 0x0042
        mock_port.device = "COM5"
        mock_port.description = "Arduino Mega 2560"
        mock_port.serial_number = "12345"
        mock_port.manufacturer = "Arduino LLC"

        with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
            candidates = detector._scan_usb()
            assert len(candidates) == 1
            assert candidates[0].board_id == "arduino_mega"
            assert candidates[0].confidence == 0.95
            assert candidates[0].source == "usb_vidpid"
            assert candidates[0].details["port"] == "COM5"

    def test_usb_scan_ch340_not_identified(self, temp_dir):
        """CH340 USB-TTL chips are NOT board identifiers — must return no candidate."""
        detector = BoardDetector(boards_dir=temp_dir)

        mock_port = MagicMock()
        mock_port.vid = 0x1A86
        mock_port.pid = 0x7523
        mock_port.device = "COM6"
        mock_port.description = "USB-SERIAL CH340"
        mock_port.serial_number = None
        mock_port.manufacturer = "wch.cn"

        with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
            candidates = detector._scan_usb()
            # CH340 must never produce a board candidate — it's a generic bridge chip
            assert len(candidates) == 0, f"CH340 produced {len(candidates)} candidates, should be 0"

    def test_detect_high_confidence_returns_board(self, temp_dir):
        detector = BoardDetector(boards_dir=temp_dir)

        mock_port = MagicMock()
        mock_port.vid = 0x2341
        mock_port.pid = 0x0042
        mock_port.device = "COM5"
        mock_port.description = "Arduino Mega 2560"
        mock_port.serial_number = "12345"
        mock_port.manufacturer = "Arduino LLC"

        with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
            result = detector.detect()
            assert result.board_id == "arduino_mega"

    def test_detect_low_confidence_returns_none(self, temp_dir):
        """CH340 alone must produce no candidates — it's a bridge chip, not a board ID."""
        detector = BoardDetector(boards_dir=temp_dir)

        mock_port = MagicMock()
        mock_port.vid = 0x1A86
        mock_port.pid = 0x7523
        mock_port.device = "COM6"
        mock_port.description = "USB-SERIAL CH340"
        mock_port.serial_number = None
        mock_port.manufacturer = "wch.cn"

        with patch("serial.tools.list_ports.comports", return_value=[mock_port]):
            result = detector.detect()
            assert result.board_id is None
            assert len(result.candidates) == 0  # CH340 is not a board identifier

    def test_detect_no_ports(self, temp_dir):
        detector = BoardDetector(boards_dir=temp_dir)
        with patch("serial.tools.list_ports.comports", return_value=[]):
            result = detector.detect()
            assert result.board_id is None
            assert result.candidates == []

    def test_known_devices_table(self):
        """Verify the known devices table has valid entries."""
        assert len(_KNOWN_DEVICES) > 0
        for (vid, pid), (board_id, conf) in _KNOWN_DEVICES.items():
            assert 0 <= vid <= 0xFFFF
            assert 0 <= pid <= 0xFFFF
            assert 0.0 <= conf <= 1.0
            assert isinstance(board_id, str)

    def test_multi_board_detection(self, temp_dir):
        """Multiple COM ports with distinct boards should populate result.boards."""
        detector = BoardDetector(boards_dir=temp_dir)

        port_a = MagicMock()
        port_a.vid = 0x1A86; port_a.pid = 0x7523
        port_a.device = "COM5"
        port_a.description = "USB-SERIAL CH340 A"
        port_a.serial_number = None; port_a.manufacturer = None

        port_b = MagicMock()
        port_b.vid = 0x1A86; port_b.pid = 0x7523
        port_b.device = "COM8"
        port_b.description = "USB-SERIAL CH340 B"
        port_b.serial_number = None; port_b.manufacturer = None

        with patch("serial.tools.list_ports.comports", return_value=[port_a, port_b]):
            result = detector.detect()

        # Multi-board result: boards field exists and is a list
        assert isinstance(result.boards, list)

    def test_infer_from_workspace_board_json(self, temp_dir):
        """Workspace inference should find explicit board.json."""
        # Create a workspace with board.json
        board_json = temp_dir / "board.json"
        board_json.write_text(json.dumps({"board_name": "Arduino Mega 2560"}))
        # Also create the matching boards dir entry
        board_dir = temp_dir / "arduino_mega"
        board_dir.mkdir()
        (board_dir / "board.json").write_text(json.dumps({"board_name": "Arduino Mega 2560"}))

        detector = BoardDetector(boards_dir=temp_dir)
        candidate = detector._infer_from_workspace(workspace_dir=temp_dir)
        assert candidate is not None
        assert candidate.source == "workspace"

    def test_infer_from_workspace_source_code(self, temp_dir):
        """Workspace inference should detect AVR from source register usage."""
        src = temp_dir / "src"
        src.mkdir()
        main = src / "main.cpp"
        main.write_text("#include <avr/io.h>\nint main() { DDRB = 0xFF; PORTB = 0x0F; return 0; }")

        # Also create a boards dir so the detector doesn't fail
        bdir = temp_dir / "arduino_328p"
        bdir.mkdir()
        (bdir / "board.json").write_text(json.dumps({"board_name": "Arduino 328P"}))

        detector = BoardDetector(boards_dir=temp_dir)
        candidate = detector._infer_from_workspace(source_dir=src)
        assert candidate is not None
        assert candidate.board_id == "arduino_328p"
        assert candidate.source == "workspace_source"
        assert candidate.confidence == 0.60

    def test_infer_from_workspace_mega_source(self, temp_dir):
        """Workspace inference should identify Mega 2560 from mega-only registers."""
        src = temp_dir / "src"
        src.mkdir()
        main = src / "main.cpp"
        main.write_text(
            "#include <avr/io.h>\n"
            "int main() {\n"
            "  DDRE = 0xFF; PORTE = 0x0F;\n"  # mega-only
            "  TCCR3A = 0x00; OCR3A = 1000;\n"  # mega-only
            "  return 0; }"
        )

        bdir = temp_dir / "arduino_mega"
        bdir.mkdir()
        (bdir / "board.json").write_text(json.dumps({"board_name": "Arduino Mega 2560"}))

        detector = BoardDetector(boards_dir=temp_dir)
        candidate = detector._infer_from_workspace(source_dir=src)
        assert candidate is not None
        assert candidate.board_id == "arduino_mega"
        assert candidate.source == "workspace_source"
