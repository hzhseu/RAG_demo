import sys
from pathlib import Path
from nordrag.cli import main as builder
from nordrag.launcher import main as chat

if __name__ == "__main__":
    raise SystemExit(builder() if "builder" in Path(sys.executable).stem else chat())
