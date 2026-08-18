"""Package data resource locator.

Dev (source checkout) and installed (pip wheel) modes are unified: all data
lives under ``firmforge/data/``, so ``Path(__file__).parent.parent / "data"``
resolves identically in both modes. No cwd dependency — safe to run the
toolchain or MCP server from any directory.
"""

from pathlib import Path

_PKG = Path(__file__).resolve().parent.parent  # .../firmforge/


def data_dir() -> Path:
    """Root of bundled package data (boards, knowledge, vendor manifests)."""
    return _PKG / "data"


def boards_dir() -> Path:
    """Board definitions (board.yaml per board) + bundled example apps."""
    return data_dir() / "boards"


def knowledge_dir() -> Path:
    """Chip knowledge: knowledge/reference/<platform>/<chip>/registers.json etc."""
    return data_dir() / "knowledge"


def vendor_dir() -> Path:
    """Toolchain download manifests (vendor/manifests/...)."""
    return data_dir() / "vendor"


def manifests_dir() -> Path:
    return vendor_dir() / "manifests"
