"""Unit tests for bootloader baud fallback in ArduinoFlashProvider."""

import pytest
from unittest.mock import patch, MagicMock


class TestBootloaderBaudFallback:
    """Tests that avrdude retries with fallback baud when primary fails."""

    @pytest.fixture
    def board_config(self):
        return {
            "board_name": "Arduino Nano",
            "mcu": {"chip": "ATmega328P"},
            "bootloader": {"baud_rate": 57600, "fallback_bauds": [115200, 19200]},
            "pins": {"led_builtin": 13},
            "specs": {"flash": "32 KB", "clock": "16 MHz"},
            "features": {"gpio": True, "uart": True},
        }

    def test_get_baud_fallbacks_from_board_config(self, board_config):
        """Board config bootloader.fallback_bauds should be used."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        with patch("firmforge.providers.arduino.toolchain.resolve_toolchain"):
            fp = ArduinoFlashProvider(board_config)
            fallbacks = fp._get_baud_fallbacks()
            assert 115200 in fallbacks
            assert 19200 in fallbacks

    def test_get_baud_fallbacks_default(self):
        """Without board config, use default BOOTLOADER_BAUD_FALLBACKS."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        config = {"mcu": {"chip": "ATmega328P"}}
        with patch("firmforge.providers.arduino.toolchain.resolve_toolchain"):
            fp = ArduinoFlashProvider(config)
            fallbacks = fp._get_baud_fallbacks()
            assert fallbacks == [57600, 19200]

    def test_resolve_baud_map(self):
        """_resolve_baud returns correct primary baud for known parts."""
        from firmforge.providers.arduino.flash import ArduinoFlashProvider

        config = {"mcu": {"chip": "ATmega328P"}}
        with patch("firmforge.providers.arduino.toolchain.resolve_toolchain"):
            fp = ArduinoFlashProvider(config)
            assert fp._resolve_baud() == 115200
