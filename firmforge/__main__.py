"""FirmForge entry point — allows 'python -m firmforge' to invoke CLI."""

import sys
from firmforge.adapters.cli import main

if __name__ == "__main__":
    sys.exit(main())
