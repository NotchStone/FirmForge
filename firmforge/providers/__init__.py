"""MCU Providers -- hardware abstraction boundary.

Architectural contract (R6): New MCU platforms register here.
NEVER modify Core layer (pipeline_runner) to add a platform.

Provider registry -- add one entry per new platform:
  _REGISTRY = {
      "arduino": { "build": "firmforge.providers.arduino.build:ArduinoBuildProvider",
                   "flash": "firmforge.providers.arduino.flash:ArduinoFlashProvider" },
  }
"""

from __future__ import annotations

import importlib
from typing import Any

from firmforge.providers.base import BuildProvider, FlashProvider, TestProvider
from firmforge.providers.com_port import ComPort, com_port_clean_close

__all__ = [
    "BuildProvider", "FlashProvider", "TestProvider",
    "get_build_provider", "get_flash_provider", "get_test_provider",
    "ComPort", "com_port_clean_close",
]

_PROVIDER_REGISTRY: dict[str, dict[str, str]] = {
    "arduino": {
        "build": "firmforge.providers.arduino.build:ArduinoBuildProvider",
        "flash": "firmforge.providers.arduino.flash:ArduinoFlashProvider",
    },
}


def _resolve(module_path: str, class_name: str) -> Any:
    mod = importlib.import_module(module_path)
    return getattr(mod, class_name)


def get_build_provider(platform: str, board_config: dict) -> BuildProvider:
    entry = _PROVIDER_REGISTRY.get(platform)
    if not entry:
        raise ValueError(f"Unsupported platform: {platform}")
    module_path, class_name = entry["build"].split(":")
    cls = _resolve(module_path, class_name)
    return cls(board_config)


def get_flash_provider(platform: str, board_config: dict) -> FlashProvider:
    entry = _PROVIDER_REGISTRY.get(platform)
    if not entry:
        raise ValueError(f"Unsupported platform: {platform}")
    module_path, class_name = entry["flash"].split(":")
    cls = _resolve(module_path, class_name)
    return cls(board_config)


__all__ = ["BuildProvider", "FlashProvider", "TestProvider",
           "get_build_provider", "get_flash_provider"]
