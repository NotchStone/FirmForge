"""Adapters -- external interfaces.

Modules:
- CLI: ff detect / ff verify / ff build / ff flash (argparse)
- MCP Server: stdio(本地)+SSE(远程) (stage 4+)
- VS Code Extension: graphical shell (stage 4+)
"""

from firmforge.adapters.cli import main

__all__ = ["main"]
