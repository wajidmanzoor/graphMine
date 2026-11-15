from pathlib import Path
import sys

STUDIO = Path(__file__).resolve().parents[1]
REPO = STUDIO.parent
sys.path[:0] = [str(STUDIO), str(REPO / "agent"), str(REPO / "python/graphmine")]
