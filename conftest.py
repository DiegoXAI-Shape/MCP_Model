import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
SRC = REPO_ROOT / "src"
BACKEND = SRC / "backend"

for p in [str(BACKEND), str(SRC), str(REPO_ROOT)]:
    if p not in sys.path:
        sys.path.insert(0, p)
